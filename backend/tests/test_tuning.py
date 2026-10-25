import numpy as np
import pytest

from app.evaluation.benchmark import ABLATIONS, run_benchmark
from app.evaluation.tuning import (
    CVSettings,
    cross_validate,
    select_config,
    stratified_folds,
    weight_grid,
)
from app.retrieval import HybridSearchEngine, SearchConfig
from tests.conftest import make_hashing_embedder


def test_weight_grid_covers_simplex():
    grid = weight_grid(0.1)
    assert len(grid) == 65  # C(12, 2) = 66 points minus the seedless (0, 0, 1)
    assert all(sum(w.values()) == pytest.approx(1.0) for w in grid)
    assert {"dense": 0.4, "bm25": 0.4, "graph": 0.2} in [
        {k: round(v, 10) for k, v in w.items()} for w in grid
    ]
    assert {"dense": 0.0, "bm25": 0.0, "graph": 1.0} not in grid
    assert len(weight_grid(0.5)) == 5
    with pytest.raises(ValueError):
        weight_grid(0.3)


def test_stratified_folds_partition_and_balance():
    categories = ["a"] * 12 + ["b"] * 13 + ["c"] * 12
    folds = stratified_folds(categories, 5, seed=0)
    flat = np.concatenate(folds)
    assert sorted(flat.tolist()) == list(range(37))  # a partition
    for fold in folds:
        counts = {c: sum(categories[i] == c for i in fold) for c in "abc"}
        assert all(2 <= n <= 3 for n in counts.values())  # each category spread evenly
    assert [f.tolist() for f in folds] == [f.tolist() for f in stratified_folds(categories, 5, seed=0)]
    assert [f.tolist() for f in folds] != [f.tolist() for f in stratified_folds(categories, 5, seed=1)]
    with pytest.raises(ValueError):
        stratified_folds(categories, 1, seed=0)


def test_selection_uses_only_training_queries():
    # Config 0 is best on train, config 1 is best only on the held-out query.
    objective = np.array([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    assert select_config(objective, np.array([0, 1]), tie_break=[0, 0]) == 0
    # Changing held-out scores must not change the selection (no leakage).
    objective[1, 2] = 100.0
    assert select_config(objective, np.array([0, 1]), tie_break=[0, 0]) == 0


def test_selection_ties_break_toward_default():
    objective = np.ones((3, 4))
    assert select_config(objective, np.arange(4), tie_break=[0.5, 0.1, 0.3]) == 1


@pytest.fixture(scope="module")
def engine(billing_symbols):
    return HybridSearchEngine(billing_symbols, make_hashing_embedder())


def test_cross_validate_produces_out_of_fold_scores(engine, billing_dataset):
    settings = CVSettings(folds=4, repeats=2, step=0.25)
    result = cross_validate(
        engine,
        billing_dataset,
        SearchConfig(),
        name="tuned",
        base_name="Dense + BM25 + Graph",
        metrics=("MRR@5", "NDCG@5"),
        settings=settings,
    )
    n = len(billing_dataset.queries)
    assert result.per_query["NDCG@5"].shape == (n,)
    assert ((result.per_query["NDCG@5"] >= 0) & (result.per_query["NDCG@5"] <= 1)).all()
    assert len(result.selections) == 8
    assert sum(s.n_test for s in result.selections) == 2 * n
    assert result.grid_size == len(weight_grid(0.25))
    assert [g for g, _ in result.sensitivity] == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
    # The in-sample optimum is an upper bound on what CV can achieve.
    assert result.in_sample_best[1] >= result.mean("NDCG@5") - 1e-12


def test_cross_validate_requires_all_pillars(engine, billing_dataset):
    with pytest.raises(ValueError):
        cross_validate(
            engine,
            billing_dataset,
            SearchConfig(use_graph=False),
            name="x",
            base_name="y",
            metrics=("NDCG@5",),
        )


def test_benchmark_reports_cross_validation(engine, billing_dataset):
    report = run_benchmark(
        billing_dataset,
        engine,
        configs={k: v for k, v in ABLATIONS.items() if not v.use_reranker},
        n_resamples=100,
        cv=CVSettings(folds=3, repeats=1, step=0.25),
    )
    assert [cv.name for cv in report.cv_results] == ["Dense + BM25 + Graph (CV-tuned)"]
    references = {(c.baseline, c.metric) for c in report.cv_comparisons}
    assert references == {(b, m) for b in ("BM25", "Dense + BM25 + Graph") for m in ("MRR@5", "NDCG@5")}
    markdown = report.to_markdown()
    assert "## Cross-validated fusion weights" in markdown
    assert "### Weights selected across folds" in markdown
    assert report.to_json()["cross_validation"][0]["base"] == "Dense + BM25 + Graph"
