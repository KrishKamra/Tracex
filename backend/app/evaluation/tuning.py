"""Cross-validated tuning of the weighted-RRF fusion weights.

Choosing weights on the same queries used to report results is test-set
overfitting. Instead, weights are selected by repeated stratified k-fold
cross-validation, and every query is scored only by weights chosen without it:

    for repeat r = 1..R:
        split queries into k folds, stratified by category (seed + r)
        for fold f:
            w*_f = argmax_{w in grid} mean_{q in train(f)} NDCG@5(q; w)
            record metrics(q; w*_f) for each held-out q in fold f
    out-of-fold score(q) = mean over repeats

The grid is the simplex {(w_dense, w_bm25, w_graph) : w_i in {0, s, 2s, ..., 1},
sum w_i = 1, w_dense + w_bm25 > 0}. Ties are broken toward the untuned default
weights (L1 distance), so a flat objective never drifts to an arbitrary corner.

Efficiency: first-stage rankings (dense, BM25) do not depend on the weights, so
each query is retrieved once. Every grid point only re-runs graph expansion,
RRF and the (pair-cached) reranker, which makes the per-query metric matrix
M[w, q] cheap. Fold selection then only indexes into M.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from app.evaluation.dataset import EvalDataset
from app.evaluation.metrics import evaluate_run
from app.retrieval.engine import DEFAULT_WEIGHTS, HybridSearchEngine, SearchConfig

Weights = Mapping[str, float]
PILLARS = ("dense", "bm25", "graph")


@dataclass(frozen=True)
class CVSettings:
    folds: int = 5
    repeats: int = 3
    step: float = 0.1
    objective: str = "NDCG@5"
    seed: int = 0


@dataclass(frozen=True)
class FoldSelection:
    repeat: int
    fold: int
    weights: Weights
    train_score: float
    test_score: float
    n_test: int


@dataclass
class CVResult:
    name: str
    base_name: str
    settings: CVSettings
    per_query: dict[str, np.ndarray]
    selections: list[FoldSelection]
    grid_size: int
    sensitivity: list[tuple[float, float]]  # (w_graph, objective) along w_dense = w_bm25
    in_sample_best: tuple[Weights, float]

    def mean(self, metric: str) -> float:
        return float(self.per_query[metric].mean())

    @property
    def selected_weights(self) -> Counter[tuple[float, float, float]]:
        """How often each weight vector was chosen across all folds and repeats."""
        return Counter(tuple(s.weights[p] for p in PILLARS) for s in self.selections)


def weight_grid(step: float = 0.1) -> list[dict[str, float]]:
    n = round(1 / step)
    if n < 1 or not np.isclose(n * step, 1.0):
        raise ValueError("step must divide 1 evenly (e.g. 0.1, 0.125, 0.25)")
    grid = []
    for g in range(n + 1):
        for d in range(n + 1 - g):
            b = n - g - d
            if d + b > 0:  # graph expansion needs at least one seed pillar
                grid.append({"dense": d / n, "bm25": b / n, "graph": g / n})
    return grid


def stratified_folds(categories: Sequence[str], k: int, seed: int) -> list[np.ndarray]:
    """Deal each category's shuffled queries round-robin into ``k`` test folds."""
    if not 2 <= k <= len(categories):
        raise ValueError(f"need 2 <= k <= {len(categories)} folds, got {k}")
    rng = np.random.default_rng(seed)
    folds: list[list[int]] = [[] for _ in range(k)]
    offset = 0
    for category in dict.fromkeys(categories):
        members = [i for i, c in enumerate(categories) if c == category]
        rng.shuffle(members)
        for j, index in enumerate(members):
            folds[(offset + j) % k].append(index)
        offset += len(members)
    return [np.array(sorted(f), dtype=np.int64) for f in folds]


def _distance_to_default(weights: Weights) -> float:
    total = sum(DEFAULT_WEIGHTS.values())
    return sum(abs(weights[p] - DEFAULT_WEIGHTS[p] / total) for p in PILLARS)


def select_config(objective: np.ndarray, train: np.ndarray, tie_break: Sequence[float]) -> int:
    """Index of the grid point maximizing the mean objective over ``train`` queries."""
    means = objective[:, train].mean(axis=1)
    best = np.flatnonzero(np.isclose(means, means.max(), rtol=0, atol=1e-12))
    return int(min(best, key=lambda c: (tie_break[c], c)))


def score_weights(
    engine: HybridSearchEngine,
    dataset: EvalDataset,
    base: SearchConfig,
    weight_list: Sequence[Weights],
    metrics: Sequence[str],
    depth: int = 10,
) -> dict[str, np.ndarray]:
    """Per-query metrics for every weight vector: ``{metric: (len(weight_list), n_queries)}``."""
    pillars = [engine.retrieve(q.text, base) for q in dataset.queries]
    out = {m: np.zeros((len(weight_list), len(dataset.queries))) for m in metrics}
    for row, weights in enumerate(weight_list):
        config = replace(base, weights=dict(weights))
        runs = {
            q.query_id: engine.fuse(p, config, top_k=depth).ranked_ids
            for q, p in zip(dataset.queries, pillars, strict=True)
        }
        for metric, values in evaluate_run(runs, dataset.qrels, metrics).items():
            out[metric][row] = values
    return out


def cross_validate(
    engine: HybridSearchEngine,
    dataset: EvalDataset,
    base: SearchConfig,
    *,
    name: str,
    base_name: str,
    metrics: Sequence[str],
    settings: CVSettings | None = None,
    depth: int = 10,
) -> CVResult:
    settings = settings or CVSettings()
    if not (base.use_dense and base.use_bm25 and base.use_graph):
        raise ValueError("weight tuning needs a base configuration with all three pillars enabled")
    if settings.objective not in metrics:
        metrics = (*metrics, settings.objective)

    grid = weight_grid(settings.step)
    line = [
        {"dense": (1 - g) / 2, "bm25": (1 - g) / 2, "graph": g} for g in np.round(np.arange(0, 0.65, 0.1), 2)
    ]
    scores = score_weights(engine, dataset, base, grid + line, metrics, depth)
    grid_scores = {m: v[: len(grid)] for m, v in scores.items()}
    objective = grid_scores[settings.objective]
    tie_break = [_distance_to_default(w) for w in grid]

    n = len(dataset.queries)
    categories = [q.category for q in dataset.queries]
    oof = {m: np.zeros(n) for m in metrics}
    selections = []
    everyone = np.arange(n)
    for repeat in range(settings.repeats):
        for fold, test in enumerate(stratified_folds(categories, settings.folds, settings.seed + repeat)):
            train = np.setdiff1d(everyone, test)
            chosen = select_config(objective, train, tie_break)
            for m in metrics:
                oof[m][test] += grid_scores[m][chosen, test]
            selections.append(
                FoldSelection(
                    repeat,
                    fold,
                    grid[chosen],
                    float(objective[chosen, train].mean()),
                    float(objective[chosen, test].mean()),
                    len(test),
                )
            )
    per_query = {m: v / settings.repeats for m, v in oof.items()}

    best_in_sample = select_config(objective, everyone, tie_break)
    sensitivity = [
        (w["graph"], float(scores[settings.objective][len(grid) + i].mean())) for i, w in enumerate(line)
    ]
    return CVResult(
        name=name,
        base_name=base_name,
        settings=settings,
        per_query=per_query,
        selections=selections,
        grid_size=len(grid),
        sensitivity=sensitivity,
        in_sample_best=(grid[best_in_sample], float(objective[best_in_sample].mean())),
    )
