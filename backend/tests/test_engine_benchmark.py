import json

import numpy as np
import pytest

from app.evaluation.benchmark import ABLATIONS, BASELINE, DEFAULT_METRICS, run_benchmark
from app.evaluation.dataset import EvalDataset, EvalQuery, load_dataset, validate_against_corpus
from app.retrieval import CrossEncoderReranker, HybridSearchEngine, SearchConfig
from tests.conftest import BILLING_DATASET, make_hashing_embedder


class KeywordCrossEncoder:
    """Scores a pair by query-token overlap, so reranking is observable and deterministic."""

    def predict(self, pairs, **kwargs):
        return np.array([len(set(q.lower().split()) & set(t.lower().split())) for q, t in pairs], dtype=float)


@pytest.fixture(scope="module")
def engine(billing_symbols):
    reranker = CrossEncoderReranker("keyword", device="cpu", loader=lambda *a: KeywordCrossEncoder())
    return HybridSearchEngine(billing_symbols, make_hashing_embedder(), reranker=reranker)


def test_search_returns_explainable_hits(engine):
    result = engine.search("check_limit", top_k=5)
    top = result.hits[0]
    assert top.symbol_id == "billing/limits.py::check_limit"
    assert top.ranks["bm25"] == 1
    assert "bm25" in top.match_origin
    assert {"check_limit", "check", "limit"} <= set(top.matched_terms)
    assert sum(top.contributions.values()) == pytest.approx(top.rrf_score)
    assert {"embedding_ms", "dense_ms", "bm25_ms", "ast_graph_ms", "rrf_ms", "total_ms"} <= set(
        result.timings_ms
    )
    assert [h.rank for h in result.hits] == [1, 2, 3, 4, 5]


def test_pillar_toggles(engine):
    bm25_only = engine.search("check_limit", config=SearchConfig(use_dense=False, use_graph=False))
    assert all(h.match_origin == ("bm25",) for h in bm25_only.hits)
    assert "embedding_ms" not in bm25_only.timings_ms
    with pytest.raises(ValueError):
        SearchConfig(use_dense=False, use_bm25=False)


def test_graph_pillar_surfaces_structural_neighbours(engine):
    result = engine.search("check_limit", top_k=20, config=SearchConfig())
    by_id = {h.symbol_id: h for h in result.hits}
    # charge_customer is the only caller of check_limit: the graph pillar ranks it.
    assert by_id["billing/payments.py::charge_customer"].ranks["graph"] is not None


def test_reranker_reorders_head(engine):
    result = engine.search("refund payment", top_k=5, config=SearchConfig(use_reranker=True))
    assert all(h.rerank_score is not None for h in result.hits)
    scores = [h.rerank_score for h in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert "rerank_ms" in result.timings_ms


def test_reranker_required_when_enabled(billing_symbols):
    bare = HybridSearchEngine(billing_symbols[:5], make_hashing_embedder())
    with pytest.raises(ValueError):
        bare.search("x", config=SearchConfig(use_reranker=True))


def test_gold_dataset_matches_corpus(billing_dataset, billing_symbols):
    validate_against_corpus(billing_dataset, [s.symbol_id for s in billing_symbols])
    assert set(billing_dataset.categories) == {"lexical", "semantic", "structural"}
    assert len(billing_dataset.queries) >= 30


def test_dataset_validation_errors(tmp_path, billing_symbols):
    raw = json.loads(BILLING_DATASET.read_text())
    raw["corpus"] = str(BILLING_DATASET.parent / raw["corpus"])
    raw["queries"] = raw["queries"][:2] + raw["queries"][:1]
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(path)

    bogus = EvalDataset("x", "", tmp_path, (EvalQuery("q", "t", "c", {"nope.py::gone": 2}),))
    with pytest.raises(ValueError, match="nope.py::gone"):
        validate_against_corpus(bogus, [s.symbol_id for s in billing_symbols])


@pytest.fixture(scope="module")
def report(engine, billing_dataset):
    return run_benchmark(billing_dataset, engine, n_resamples=300)


def test_benchmark_runs_every_ablation(report, billing_dataset):
    assert list(report.results) == list(ABLATIONS)
    for result in report.results.values():
        assert set(result.per_query) == set(DEFAULT_METRICS)
        for values in result.per_query.values():
            assert values.shape == (len(billing_dataset.queries),)
            assert ((values >= 0) & (values <= 1)).all()
    # The exact-identifier query is solved by BM25.
    bm25 = report.results[BASELINE]
    assert bm25.per_query["MRR@5"][0] == 1.0


def test_benchmark_statistics(report):
    comparisons = {(c.system, c.metric): c for c in report.comparisons}
    assert len(comparisons) == 2 * (len(ABLATIONS) - 1)
    for c in comparisons.values():
        assert 0 < c.p_value <= c.p_adjusted <= 1
    for (name, _), (low, high) in report.intervals.items():
        assert low <= report.results[name].mean("MRR@5") <= high or _ != "MRR@5"


def test_benchmark_report_rendering(report):
    markdown = report.to_markdown()
    for heading in (
        "## Effectiveness",
        "## 95% bootstrap",
        "## Significance",
        "by query category",
        "## Latency",
    ):
        assert heading in markdown
    for name in ABLATIONS:
        assert f"| {name} |" in markdown
    payload = json.loads(json.dumps(report.to_json()))
    assert set(payload["metrics"]) == set(ABLATIONS)
    assert payload["per_query"][BASELINE]["lex-01"]["ranked"][0] == "billing/limits.py::check_limit"


def test_benchmark_skips_reranker_config_without_model(billing_dataset, billing_symbols):
    engine = HybridSearchEngine(billing_symbols, make_hashing_embedder())
    report = run_benchmark(billing_dataset, engine, n_resamples=50)
    assert "Full Tracex (+ Reranker)" in report.skipped
    assert "Full Tracex (+ Reranker)" not in report.results
