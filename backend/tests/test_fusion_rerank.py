import numpy as np
import pytest

from app.retrieval import CrossEncoderReranker, weighted_rrf
from app.retrieval.rrf_fusion import normalize_weights


def test_weighted_rrf_matches_formula():
    rankings = {"dense": ["a", "b", "c"], "bm25": ["b", "d"]}
    hits = weighted_rrf(rankings, {"dense": 3, "bm25": 1}, k=60)  # normalized to 0.75 / 0.25
    by_id = {h.doc_id: h for h in hits}
    assert by_id["b"].rrf_score == pytest.approx(0.75 / 62 + 0.25 / 61)
    assert by_id["a"].rrf_score == pytest.approx(0.75 / 61)
    assert by_id["d"].rrf_score == pytest.approx(0.25 / 62)
    assert [h.doc_id for h in hits] == ["b", "a", "c", "d"]
    assert [h.rank for h in hits] == [1, 2, 3, 4]
    assert by_id["b"].ranks == {"dense": 2, "bm25": 1}
    assert by_id["c"].ranks == {"dense": 3, "bm25": None}
    assert by_id["b"].match_origin == ("dense", "bm25")
    assert by_id["d"].match_origin == ("bm25",)


def test_rrf_ties_break_by_best_rank_then_id():
    hits = weighted_rrf({"x": ["p", "q"], "y": ["q", "p"]}, k=60)
    assert [h.doc_id for h in hits] == ["p", "q"]
    assert weighted_rrf({"x": ["b"], "y": ["a"]})[0].doc_id == "a"


def test_rrf_top_k_and_duplicates():
    hits = weighted_rrf({"x": ["a", "a", "b", "c"]}, top_k=2)
    assert [h.doc_id for h in hits] == ["a", "b"]
    assert hits[1].ranks["x"] == 2


def test_weight_normalization_and_validation():
    assert normalize_weights({"dense": 0.4, "bm25": 0.4, "graph": 0.2}, ["dense", "bm25"]) == {
        "dense": 0.5,
        "bm25": 0.5,
    }
    with pytest.raises(ValueError):
        normalize_weights({"a": -1}, ["a"])
    with pytest.raises(ValueError):
        normalize_weights({"a": 0}, ["a"])
    with pytest.raises(ValueError):
        weighted_rrf({"a": ["x"]}, k=0)


class FakeCrossEncoder:
    def __init__(self):
        self.kwargs = None

    def predict(self, pairs, **kwargs):
        self.kwargs = kwargs
        return np.array([2.0 if "refund" in text else -1.0 for _, text in pairs])


def test_reranker_sigmoid_scores_and_order():
    backend = FakeCrossEncoder()
    reranker = CrossEncoderReranker("fake", device="cpu", loader=lambda *args: backend)
    order = reranker.rerank("money back", [("a", "send email"), ("b", "refund payment"), ("c", "log")])
    assert [doc for doc, _ in order] == ["b", "a", "c"]  # stable for tied a / c
    assert order[0][1] == pytest.approx(1 / (1 + np.exp(-2.0)))
    assert backend.kwargs["activation_fn"](5.0) == 5.0  # raw logits requested
    assert reranker.score("q", []).shape == (0,)
