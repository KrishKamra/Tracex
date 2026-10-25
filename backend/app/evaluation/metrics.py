"""Information-retrieval effectiveness metrics (per query, cut-off K).

Relevance judgements (qrels) map doc id -> graded relevance; grade >= 1 is
relevant. Binary metrics threshold at 1; NDCG uses the grades directly.

    RR@K        = 1 / rank of the first relevant doc in the top K (0 if none)
    MRR@K       = mean_q RR@K
    Recall@K    = |relevant in top K| / |relevant|
    P@K         = |relevant in top K| / K
    Hit@K       = 1 if any relevant doc is in the top K
    AP@K        = (1 / min(|relevant|, K)) * sum_{p <= K, d_p relevant} P@p
    DCG@K       = sum_{p=1}^{K} (2^{rel_p} - 1) / log2(p + 1)
    NDCG@K      = DCG@K / IDCG@K   (IDCG: DCG of the ideal ordering)
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence

import numpy as np

Qrels = Mapping[str, int]
MetricFn = Callable[[Sequence[str], Qrels, int], float]


def _top(ranked: Sequence[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("k must be >= 1")
    return list(dict.fromkeys(ranked))[:k]


def _relevant(qrels: Qrels) -> set[str]:
    relevant = {d for d, grade in qrels.items() if grade > 0}
    if not relevant:
        raise ValueError("a query needs at least one relevant document")
    return relevant


def reciprocal_rank(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    relevant = _relevant(qrels)
    for position, doc in enumerate(_top(ranked, k), start=1):
        if doc in relevant:
            return 1.0 / position
    return 0.0


def recall_at_k(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    relevant = _relevant(qrels)
    return sum(d in relevant for d in _top(ranked, k)) / len(relevant)


def precision_at_k(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    relevant = _relevant(qrels)
    return sum(d in relevant for d in _top(ranked, k)) / k


def hit_at_k(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    relevant = _relevant(qrels)
    return float(any(d in relevant for d in _top(ranked, k)))


def average_precision_at_k(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    relevant = _relevant(qrels)
    hits, total = 0, 0.0
    for position, doc in enumerate(_top(ranked, k), start=1):
        if doc in relevant:
            hits += 1
            total += hits / position
    return total / min(len(relevant), k)


def dcg(grades: Sequence[int], k: int) -> float:
    return sum((2**g - 1) / math.log2(p + 1) for p, g in enumerate(grades[:k], start=1))


def ndcg_at_k(ranked: Sequence[str], qrels: Qrels, k: int) -> float:
    _relevant(qrels)
    gains = [qrels.get(d, 0) for d in _top(ranked, k)]
    ideal = dcg(sorted(qrels.values(), reverse=True), k)
    return dcg(gains, k) / ideal


METRICS: dict[str, MetricFn] = {
    "MRR": reciprocal_rank,
    "NDCG": ndcg_at_k,
    "Recall": recall_at_k,
    "P": precision_at_k,
    "MAP": average_precision_at_k,
    "Hit": hit_at_k,
}
_METRIC_RE = re.compile(r"^(?P<name>[A-Za-z]+)@(?P<k>\d+)$")


def parse_metric(spec: str) -> tuple[MetricFn, int]:
    """``"NDCG@5"`` -> (ndcg_at_k, 5)."""
    match = _METRIC_RE.match(spec)
    if match is None or match["name"] not in METRICS:
        raise ValueError(f"unknown metric {spec!r}; expected one of {sorted(METRICS)} as NAME@K")
    return METRICS[match["name"]], int(match["k"])


def evaluate_run(
    run: Mapping[str, Sequence[str]], qrels: Mapping[str, Qrels], metrics: Sequence[str]
) -> dict[str, np.ndarray]:
    """Per-query metric values, in ``qrels`` query order. Missing runs score 0."""
    parsed = {spec: parse_metric(spec) for spec in metrics}
    return {
        spec: np.array([fn(run.get(qid, []), judged, k) for qid, judged in qrels.items()], dtype=np.float64)
        for spec, (fn, k) in parsed.items()
    }
