import math

import numpy as np
import pytest

from app.evaluation.metrics import (
    average_precision_at_k,
    dcg,
    evaluate_run,
    hit_at_k,
    ndcg_at_k,
    parse_metric,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

RANKED = ["a", "b", "c", "d", "e"]
QRELS = {"b": 2, "d": 1, "z": 1}  # z is relevant but never retrieved


def test_reciprocal_rank():
    assert reciprocal_rank(RANKED, QRELS, 5) == 0.5
    assert reciprocal_rank(RANKED, QRELS, 1) == 0.0
    assert reciprocal_rank(["b"], QRELS, 5) == 1.0


def test_recall_precision_hit():
    assert recall_at_k(RANKED, QRELS, 5) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, QRELS, 3) == pytest.approx(1 / 3)
    assert precision_at_k(RANKED, QRELS, 5) == pytest.approx(2 / 5)
    # P@K divides by K even when fewer than K documents were returned.
    assert precision_at_k(["b"], QRELS, 5) == pytest.approx(1 / 5)
    assert hit_at_k(RANKED, QRELS, 1) == 0.0
    assert hit_at_k(RANKED, QRELS, 2) == 1.0


def test_average_precision():
    # Relevant at ranks 2 and 4: (1/2 + 2/4) / min(|rel| = 3, K = 5)
    assert average_precision_at_k(RANKED, QRELS, 5) == pytest.approx((0.5 + 0.5) / 3)
    assert average_precision_at_k(["b", "d", "z"], QRELS, 3) == pytest.approx(1.0)


def test_ndcg_graded():
    expected_dcg = (2**2 - 1) / math.log2(3) + (2**1 - 1) / math.log2(5)
    ideal = (2**2 - 1) / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
    assert dcg([0, 2, 0, 1, 0], 5) == pytest.approx(expected_dcg)
    assert ndcg_at_k(RANKED, QRELS, 5) == pytest.approx(expected_dcg / ideal)
    assert ndcg_at_k(["b", "d", "z"], QRELS, 3) == pytest.approx(1.0)
    # Swapping the grade-2 and grade-1 documents must lower NDCG.
    assert ndcg_at_k(["d", "b", "z"], QRELS, 3) < 1.0


def test_duplicate_ranked_ids_count_once():
    assert recall_at_k(["b", "b", "b"], QRELS, 3) == pytest.approx(1 / 3)
    assert precision_at_k(["b", "b", "d"], QRELS, 2) == pytest.approx(1.0)


def test_metric_validation():
    with pytest.raises(ValueError):
        reciprocal_rank(RANKED, {"a": 0}, 5)
    with pytest.raises(ValueError):
        recall_at_k(RANKED, QRELS, 0)
    with pytest.raises(ValueError):
        parse_metric("BLEU@5")
    with pytest.raises(ValueError):
        parse_metric("MRR")
    assert parse_metric("NDCG@10") == (ndcg_at_k, 10)


def test_evaluate_run_per_query_and_missing_runs():
    qrels = {"q1": {"a": 1}, "q2": {"x": 1}}
    values = evaluate_run({"q1": ["a", "b"]}, qrels, ["MRR@5", "Recall@1"])
    np.testing.assert_array_equal(values["MRR@5"], [1.0, 0.0])  # q2 has no run
    np.testing.assert_array_equal(values["Recall@1"], [1.0, 0.0])
