"""Ablation benchmark for the Tracex hybrid retrieval pipeline.

Runs every gold query through each ablation configuration over one shared
index and reports:

* effectiveness: MRR@K, NDCG@K, Recall@K, P@K, MAP@K, Hit@K (means over queries)
* uncertainty:   95% percentile-bootstrap CIs for the headline metrics
* significance:  paired randomization tests vs. the BM25 baseline,
                 Holm-Bonferroni corrected across all comparisons
* breakdown:     NDCG per query category (lexical / semantic / structural)
* efficiency:    per-query latency p50 / p95 / mean
* index quality: chunk counts, graph edges, call-resolution rate
* tuning:        RRF weights chosen by repeated stratified k-fold CV, scored
                 out-of-fold and tested against BM25 and the untuned pipeline

Usage::

    uv run python -m app.evaluation.benchmark                      # default dataset, real models
    uv run python -m app.evaluation.benchmark --no-reranker --output eval/reports/run.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.evaluation.dataset import EvalDataset, load_dataset, validate_against_corpus
from app.evaluation.metrics import evaluate_run
from app.evaluation.stats import bootstrap_ci, holm_bonferroni, paired_randomization_test
from app.evaluation.tuning import PILLARS, CVResult, CVSettings, cross_validate
from app.retrieval.engine import HybridSearchEngine, SearchConfig

ABLATIONS: dict[str, SearchConfig] = {
    "BM25": SearchConfig(use_dense=False, use_graph=False),
    "Dense": SearchConfig(use_bm25=False, use_graph=False),
    "Dense + BM25": SearchConfig(use_graph=False),
    "Dense + BM25 + Graph": SearchConfig(),
    "Full Tracex (+ Reranker)": SearchConfig(use_reranker=True),
}
BASELINE = "BM25"
DEFAULT_METRICS = ("MRR@5", "NDCG@5", "Recall@5", "P@5", "MAP@5", "Hit@1", "Recall@10")
HEADLINE_METRICS = ("MRR@5", "NDCG@5", "Recall@5")
CATEGORY_METRIC = "NDCG@5"
SIGNIFICANCE_LEVEL = 0.05
CV_BASES = ("Dense + BM25 + Graph", "Full Tracex (+ Reranker)")
DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "eval" / "datasets" / "billing_service.json"


@dataclass
class ConfigResult:
    name: str
    config: SearchConfig
    per_query: dict[str, np.ndarray]
    latencies_ms: np.ndarray
    runs: dict[str, list[str]]

    def mean(self, metric: str) -> float:
        return float(self.per_query[metric].mean())


@dataclass(frozen=True)
class Comparison:
    system: str
    metric: str
    delta: float
    p_value: float
    p_adjusted: float
    baseline: str = BASELINE

    @property
    def significant(self) -> bool:
        return self.p_adjusted < SIGNIFICANCE_LEVEL


@dataclass
class BenchmarkReport:
    dataset: EvalDataset
    metrics: tuple[str, ...]
    results: dict[str, ConfigResult]
    intervals: dict[tuple[str, str], tuple[float, float]]
    comparisons: list[Comparison]
    index_info: dict[str, object]
    skipped: dict[str, str] = field(default_factory=dict)
    cv_results: list[CVResult] = field(default_factory=list)
    cv_comparisons: list[Comparison] = field(default_factory=list)

    # -- rendering ---------------------------------------------------------- #
    def category_means(self, name: str, metric: str = CATEGORY_METRIC) -> dict[str, float]:
        values = self.results[name].per_query[metric]
        categories = np.array([q.category for q in self.dataset.queries])
        return {c: float(values[categories == c].mean()) for c in self.dataset.categories}

    def to_markdown(self) -> str:
        names = list(self.results)
        n = len(self.dataset.queries)
        info = self.index_info
        out = [
            f"# Tracex Retrieval Benchmark: `{self.dataset.name}`",
            "",
            self.dataset.description,
            "",
            f"- **Queries:** {n} ({', '.join(f'{c}: {self._count(c)}' for c in self.dataset.categories)}); "
            f"**judgements:** {sum(len(q.qrels) for q in self.dataset.queries)}",
            f"- **Corpus:** {info['files']} files, {info['chunks']} AST chunks",
            f"- **Embedding model:** `{info['embedding_model']}`; **reranker:** `{info['reranker_model']}`; "
            f"**device:** `{info['device']}`",
            f"- **Generated:** {info['generated_at']}",
            "",
            f"## Effectiveness (mean over {n} queries)",
            "",
            "Best value per column in **bold**.",
            "",
            self._table(
                ["Configuration", *self.metrics],
                [[name, *(self._best(name, m) for m in self.metrics)] for name in names],
            ),
            "",
            "## 95% bootstrap confidence intervals",
            "",
            self._table(
                ["Configuration", *HEADLINE_METRICS],
                [
                    [name, *(self._interval(name, m) for m in HEADLINE_METRICS if m in self.metrics)]
                    for name in names
                ],
            ),
            "",
            f"## Significance vs. `{BASELINE}`",
            "",
            "Paired approximate randomization test (two-sided), Holm-Bonferroni adjusted across "
            f"all comparisons below; `*` marks p_adj < {SIGNIFICANCE_LEVEL}.",
            "",
            self._table(
                ["Configuration", "Metric", "Δ vs BM25", "p", "p_adj", ""],
                [
                    [
                        c.system,
                        c.metric,
                        f"{c.delta:+.3f}",
                        f"{c.p_value:.4f}",
                        f"{c.p_adjusted:.4f}",
                        "*" if c.significant else "",
                    ]
                    for c in self.comparisons
                ],
            ),
            "",
            f"## {CATEGORY_METRIC} by query category",
            "",
            self._table(
                ["Configuration", *(f"{c} (n={self._count(c)})" for c in self.dataset.categories)],
                [[name, *(f"{v:.3f}" for v in self.category_means(name).values())] for name in names],
            ),
            "",
            *self._cv_section(),
            "## Latency per query (ms)",
            "",
            self._table(
                ["Configuration", "p50", "p95", "mean"],
                [
                    [
                        name,
                        f"{np.percentile(r.latencies_ms, 50):.1f}",
                        f"{np.percentile(r.latencies_ms, 95):.1f}",
                        f"{r.latencies_ms.mean():.1f}",
                    ]
                    for name, r in self.results.items()
                ],
            ),
            "",
            "## Index",
            "",
            self._table(
                ["Property", "Value"],
                [
                    ["AST chunks", str(info["chunks"])],
                    ["Graph edges", ", ".join(f"{k}: {v}" for k, v in info["graph_edges"].items())],
                    [
                        "Call resolution",
                        f"{info['resolved_calls']}/{info['call_names']} ({info['resolution_rate']:.1%}); "
                        "unresolved calls are mostly builtins and third-party APIs",
                    ],
                    ["Index build (ms)", ", ".join(f"{k}: {v:.0f}" for k, v in info["build_ms"].items())],
                ],
            ),
        ]
        if self.skipped:
            out += ["", "## Skipped configurations", ""]
            out += [f"- **{name}**: {reason}" for name, reason in self.skipped.items()]
        return "\n".join(out) + "\n"

    def to_json(self) -> dict[str, object]:
        return {
            "dataset": self.dataset.name,
            "index": self.index_info,
            "metrics": {name: {m: r.mean(m) for m in self.metrics} for name, r in self.results.items()},
            "confidence_intervals": {f"{name}|{m}": list(ci) for (name, m), ci in self.intervals.items()},
            "significance": [c.__dict__ | {"significant": c.significant} for c in self.comparisons],
            "by_category": {name: self.category_means(name) for name in self.results},
            "latency_ms": {
                name: {
                    "p50": float(np.percentile(r.latencies_ms, 50)),
                    "p95": float(np.percentile(r.latencies_ms, 95)),
                }
                for name, r in self.results.items()
            },
            "per_query": {
                name: {
                    q.query_id: {m: float(r.per_query[m][i]) for m in self.metrics}
                    | {"ranked": r.runs[q.query_id]}
                    for i, q in enumerate(self.dataset.queries)
                }
                for name, r in self.results.items()
            },
            "skipped": self.skipped,
            "cross_validation": [
                {
                    "name": cv.name,
                    "base": cv.base_name,
                    "settings": cv.settings.__dict__,
                    "metrics": {m: cv.mean(m) for m in self.metrics},
                    "selections": [sel.__dict__ | {"weights": dict(sel.weights)} for sel in cv.selections],
                    "sensitivity": cv.sensitivity,
                    "in_sample_best": {"weights": dict(cv.in_sample_best[0]), "score": cv.in_sample_best[1]},
                    "per_query": {
                        q.query_id: {m: float(cv.per_query[m][i]) for m in self.metrics}
                        for i, q in enumerate(self.dataset.queries)
                    },
                }
                for cv in self.cv_results
            ],
            "cv_significance": [c.__dict__ | {"significant": c.significant} for c in self.cv_comparisons],
        }

    def _cv_section(self) -> list[str]:
        if not self.cv_results:
            return []
        settings = self.cv_results[0].settings
        objective = settings.objective
        rows = []
        for cv in self.cv_results:
            rows.append(
                [
                    f"{cv.base_name} (default weights)",
                    *(self._interval(cv.base_name, m) for m in HEADLINE_METRICS),
                ]
            )
            rows.append([cv.name, *(self._interval(cv.name, m, cv.per_query[m]) for m in HEADLINE_METRICS)])
        weight_rows = []
        for cv in self.cv_results:
            for weights, count in cv.selected_weights.most_common():
                chosen = [sel for sel in cv.selections if tuple(sel.weights[p] for p in PILLARS) == weights]
                weight_rows.append(
                    [
                        cv.name,
                        "(" + ", ".join(f"{w:.1f}" for w in weights) + ")",
                        f"{count}/{len(cv.selections)}",
                        f"{np.mean([sel.train_score for sel in chosen]):.3f}",
                        f"{np.mean([sel.test_score for sel in chosen]):.3f}",
                    ]
                )
        graph_weights = [g for g, _ in self.cv_results[0].sensitivity]
        sensitivity_rows = [
            [f"{g:.1f}", *(f"{dict(cv.sensitivity)[g]:.3f}" for cv in self.cv_results)] for g in graph_weights
        ]
        oracle = [
            f"- `{cv.base_name}`: ("
            + ", ".join(f"{cv.in_sample_best[0][p]:.1f}" for p in PILLARS)
            + f") → {objective} {cv.in_sample_best[1]:.3f}"
            for cv in self.cv_results
        ]
        return [
            "## Cross-validated fusion weights",
            "",
            f"RRF weights (w_dense, w_bm25, w_graph) were selected by {settings.repeats}× repeated, "
            f"category-stratified {settings.folds}-fold cross-validation over a "
            f"{self.cv_results[0].grid_size}-point simplex grid (step {settings.step}), maximizing "
            f"{objective} on the training folds. Every query below is scored **only** by weights chosen "
            "without it (out-of-fold, averaged over repeats). Ties break toward the default (0.4, 0.4, 0.2).",
            "",
            self._table(["System", *HEADLINE_METRICS], rows),
            "",
            "Paired randomization tests, Holm-Bonferroni adjusted within this family; "
            f"`*` marks p_adj < {SIGNIFICANCE_LEVEL}.",
            "",
            self._table(
                ["System", "vs", "Metric", "Δ", "p", "p_adj", ""],
                [
                    [
                        c.system,
                        c.baseline,
                        c.metric,
                        f"{c.delta:+.3f}",
                        f"{c.p_value:.4f}",
                        f"{c.p_adjusted:.4f}",
                        "*" if c.significant else "",
                    ]
                    for c in self.cv_comparisons
                ],
            ),
            "",
            "### Weights selected across folds",
            "",
            "Stable selections across folds indicate the optimum reflects the task, not one lucky split.",
            "",
            self._table(
                ["System", "(dense, bm25, graph)", "Chosen", f"Train {objective}", f"Held-out {objective}"],
                weight_rows,
            ),
            "",
            f"### Sensitivity of {objective} to the graph weight (w_dense = w_bm25)",
            "",
            "> [!NOTE]",
            "> Descriptive, in-sample curve over all queries: it shows the shape of the trade-off and is",
            "> **not** an unbiased estimate. The cross-validated rows above are the reportable numbers.",
            "",
            self._table(["w_graph", *(cv.base_name for cv in self.cv_results)], sensitivity_rows),
            "",
            "In-sample optimum (optimistic upper bound, for reference only):",
            "",
            *oracle,
            "",
        ]

    def _count(self, category: str) -> int:
        return sum(q.category == category for q in self.dataset.queries)

    def _best(self, name: str, metric: str) -> str:
        value = self.results[name].mean(metric)
        best = max(r.mean(metric) for r in self.results.values())
        text = f"{value:.3f}"
        return f"**{text}**" if np.isclose(value, best) else text

    def _interval(self, name: str, metric: str, values: np.ndarray | None = None) -> str:
        low, high = self.intervals[(name, metric)]
        mean = float(values.mean()) if values is not None else self.results[name].mean(metric)
        return f"{mean:.3f} [{low:.3f}, {high:.3f}]"

    @staticmethod
    def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
        lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)


def run_benchmark(
    dataset: EvalDataset,
    engine: HybridSearchEngine,
    *,
    configs: Mapping[str, SearchConfig] = ABLATIONS,
    metrics: Sequence[str] = DEFAULT_METRICS,
    depth: int = 10,
    n_resamples: int = 10_000,
    seed: int = 0,
    cv: CVSettings | None = None,
) -> BenchmarkReport:
    validate_against_corpus(dataset, engine.by_id)
    runnable = {n: c for n, c in configs.items() if not (c.use_reranker and engine.reranker is None)}
    skipped = {n: "no reranker loaded" for n in configs if n not in runnable}
    if BASELINE not in runnable:
        raise ValueError(f"the {BASELINE!r} baseline configuration is required")

    # Warm-up: load models and JIT paths so the first config's latency is not inflated.
    warm = next(iter(dataset.queries)).text
    for config in runnable.values():
        engine.search(warm, top_k=depth, config=config)

    results: dict[str, ConfigResult] = {}
    for name, config in runnable.items():
        # Every config pays for its own query embeddings and cross-encoder passes.
        engine.embedder.clear_cache()
        if engine.reranker is not None:
            engine.reranker.clear_cache()
        runs, latencies = {}, []
        for query in dataset.queries:
            result = engine.search(query.text, top_k=depth, config=config)
            runs[query.query_id] = result.ranked_ids
            latencies.append(result.timings_ms["total_ms"])
        results[name] = ConfigResult(
            name, config, evaluate_run(runs, dataset.qrels, metrics), np.asarray(latencies), runs
        )

    intervals = {
        (name, m): bootstrap_ci(r.per_query[m], n_resamples=n_resamples, seed=seed)
        for name, r in results.items()
        for m in HEADLINE_METRICS
        if m in metrics
    }
    raw = {}
    baseline = results[BASELINE]
    for name, r in results.items():
        if name == BASELINE:
            continue
        for m in ("MRR@5", "NDCG@5"):
            if m in metrics:
                raw[(name, m)] = paired_randomization_test(
                    r.per_query[m], baseline.per_query[m], n_resamples=n_resamples, seed=seed
                )
    adjusted = holm_bonferroni({f"{n}|{m}": p for (n, m), p in raw.items()})
    comparisons = [
        Comparison(n, m, results[n].mean(m) - baseline.mean(m), p, adjusted[f"{n}|{m}"])
        for (n, m), p in raw.items()
    ]

    cv_results: list[CVResult] = []
    cv_raw: dict[tuple[str, str, str], float] = {}
    if cv is not None:
        for base_name in CV_BASES:
            if base_name not in results:
                continue
            tuned = cross_validate(
                engine,
                dataset,
                results[base_name].config,
                name=f"{base_name} (CV-tuned)",
                base_name=base_name,
                metrics=metrics,
                settings=cv,
                depth=depth,
            )
            cv_results.append(tuned)
            for m in HEADLINE_METRICS:
                if m in metrics:
                    intervals[(tuned.name, m)] = bootstrap_ci(
                        tuned.per_query[m], n_resamples=n_resamples, seed=seed
                    )
            for reference in (BASELINE, base_name):
                for m in ("MRR@5", "NDCG@5"):
                    if m in metrics:
                        cv_raw[(tuned.name, reference, m)] = paired_randomization_test(
                            tuned.per_query[m],
                            results[reference].per_query[m],
                            n_resamples=n_resamples,
                            seed=seed,
                        )
    cv_adjusted = holm_bonferroni({"|".join(key): p for key, p in cv_raw.items()})
    by_name = {c.name: c for c in cv_results}
    cv_comparisons = [
        Comparison(
            name,
            m,
            by_name[name].mean(m) - results[reference].mean(m),
            p,
            cv_adjusted["|".join((name, reference, m))],
            baseline=reference,
        )
        for (name, reference, m), p in cv_raw.items()
    ]

    stats = engine.graph.stats
    index_info: dict[str, object] = {
        "files": len({s.file_path for s in engine.symbols}),
        "chunks": len(engine.symbols),
        "graph_edges": dict(stats.edges),
        "call_names": stats.call_names,
        "resolved_calls": stats.resolved_calls,
        "resolution_rate": stats.resolution_rate,
        "build_ms": dict(engine.build_timings_ms),
        "embedding_model": engine.embedder.model_name,
        "reranker_model": engine.reranker.model_name if engine.reranker else "none",
        "device": engine.embedder.device,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    return BenchmarkReport(
        dataset,
        tuple(metrics),
        results,
        intervals,
        comparisons,
        index_info,
        skipped,
        cv_results,
        cv_comparisons,
    )


def main(argv: Sequence[str] | None = None) -> int:
    from app.nlp.embeddings import DEFAULT_MODEL, FALLBACK_MODELS, CodeEmbedder
    from app.retrieval.reranker import DEFAULT_RERANKER, CrossEncoderReranker

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="dense embedding model")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER)
    parser.add_argument("--no-reranker", action="store_true", help="skip the cross-encoder configuration")
    parser.add_argument("--device", default=None, help="override device detection (cuda, cpu, ...)")
    parser.add_argument("--resamples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-cv", action="store_true", help="skip cross-validated weight tuning")
    parser.add_argument("--cv-folds", type=int, default=CVSettings.folds)
    parser.add_argument("--cv-repeats", type=int, default=CVSettings.repeats)
    parser.add_argument("--cv-step", type=float, default=CVSettings.step, help="weight grid resolution")
    parser.add_argument("--output", type=Path, default=None, help="write the Markdown report here")
    parser.add_argument("--json", type=Path, default=None, help="write full per-query results here")
    args = parser.parse_args(argv)

    dataset = load_dataset(args.dataset)
    fallbacks = FALLBACK_MODELS if args.model == DEFAULT_MODEL else ()
    embedder = CodeEmbedder(args.model, fallback_models=fallbacks, device=args.device)
    reranker = None if args.no_reranker else CrossEncoderReranker(args.reranker_model, device=args.device)
    engine = HybridSearchEngine.from_repository(dataset.corpus_root, embedder, reranker=reranker)
    cv = None if args.no_cv else CVSettings(args.cv_folds, args.cv_repeats, args.cv_step, seed=args.seed)
    report = run_benchmark(dataset, engine, n_resamples=args.resamples, seed=args.seed, cv=cv)

    markdown = report.to_markdown()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
