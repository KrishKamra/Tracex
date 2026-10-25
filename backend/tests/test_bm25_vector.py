import math

import numpy as np
import pytest

from app.retrieval import BM25Index, VectorIndex

DOCS = {
    "limits": "def check_limit(account_id, amount): return usage(account_id) + amount <= cap",
    "email": "def send_email(to, body): smtp.send(to, body)",
    "webhook": "class WebhookReceiver: def handle(self, payload): check_signature(payload)",
}


@pytest.fixture
def index():
    return BM25Index().build(list(DOCS), list(DOCS.values()))


def test_bm25_score_matches_formula(index):
    k1, b = 1.2, 0.75
    tokens = {d: index.tokenizer.tokenize(t) for d, t in DOCS.items()}
    avgdl = sum(len(t) for t in tokens.values()) / len(tokens)
    n_docs, df = 3, 1  # "amount" appears only in the limits chunk
    tf, dl = tokens["limits"].count("amount"), len(tokens["limits"])
    idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
    expected = idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
    (hit,) = index.search("amount")
    assert hit.doc_id == "limits"
    assert hit.score == pytest.approx(expected)
    assert hit.matched_terms == ("amount",)


def test_bm25_subtoken_matching(index):
    # "limit" only exists as a sub-token of check_limit.
    assert [h.doc_id for h in index.search("limit")] == ["limits"]
    hits = index.search("webhook receiver signature")
    assert hits[0].doc_id == "webhook"
    assert set(hits[0].matched_terms) == {"webhook", "receiver", "signature"}


def test_bm25_excludes_non_matching_and_unknown_terms(index):
    assert index.search("zebra") == []
    assert [h.rank for h in index.search("account body payload")] == [1, 2, 3]


def test_bm25_idf_is_positive_even_for_common_terms():
    idx = BM25Index().build(["a", "b"], ["common rare", "common"])
    assert idx.idf("common") > 0
    assert idx.idf("rare") > idx.idf("common")


def test_bm25_rejects_bad_input():
    with pytest.raises(ValueError):
        BM25Index().build(["a", "a"], ["x", "y"])
    with pytest.raises(ValueError):
        BM25Index().build(["a"], ["x", "y"])


def test_vector_index_cosine_ranking():
    vectors = np.array([[1.0, 0.0], [3.0, 3.0], [0.0, 2.0]])  # unnormalized on purpose
    index = VectorIndex(["x", "diag", "y"], vectors)
    hits = index.search(np.array([0.0, 5.0]), top_k=2)
    assert [h.doc_id for h in hits] == ["y", "diag"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(math.sqrt(0.5))


def test_vector_index_ties_break_by_insertion_order():
    index = VectorIndex(["b", "a"], np.array([[1.0, 0.0], [1.0, 0.0]]))
    assert [h.doc_id for h in index.search(np.array([1.0, 0.0]))] == ["b", "a"]


def test_vector_index_validation():
    with pytest.raises(ValueError):
        VectorIndex(["a"], np.zeros((2, 3)))
    index = VectorIndex(["a"], np.ones((1, 3)))
    with pytest.raises(ValueError):
        index.search(np.ones(4))
