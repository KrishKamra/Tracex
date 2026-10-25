"""Weighted Reciprocal Rank Fusion with per-pillar explainability.

Ranks r_m(d) from each retrieval pillar m are fused as

    RRF(d) = sum_m w_m / (k + r_m(d)),    k = 60,    sum_m w_m = 1

A document absent from pillar m contributes nothing for m. RRF uses only
ranks, never raw scores, so BM25 scores (unbounded), cosine similarities in
[-1, 1] and graph expansion scores need no calibration against each other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEFAULT_RRF_K = 60


@dataclass(frozen=True, slots=True)
class FusedHit:
    doc_id: str
    rrf_score: float
    rank: int
    ranks: Mapping[str, int | None]
    contributions: Mapping[str, float]

    @property
    def match_origin(self) -> tuple[str, ...]:
        """Pillars that retrieved this document, strongest contribution first."""
        found = [(p, c) for p, c in self.contributions.items() if c > 0]
        return tuple(p for p, _ in sorted(found, key=lambda pc: (-pc[1], pc[0])))


def normalize_weights(weights: Mapping[str, float], pillars: Sequence[str]) -> dict[str, float]:
    """Restrict weights to the active pillars and rescale them to sum to 1."""
    active = {p: float(weights.get(p, 1.0)) for p in pillars}
    if any(w < 0 for w in active.values()):
        raise ValueError("RRF weights must be non-negative")
    total = sum(active.values())
    if total == 0:
        raise ValueError("at least one active pillar needs a positive weight")
    return {p: w / total for p, w in active.items()}


def weighted_rrf(
    rankings: Mapping[str, Sequence[str]],
    weights: Mapping[str, float] | None = None,
    *,
    k: int = DEFAULT_RRF_K,
    top_k: int | None = None,
) -> list[FusedHit]:
    """Fuse ranked doc-id lists (best first) from several pillars.

    Ties are broken by best individual rank, then by doc id, so fusion is fully
    deterministic.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    pillars = list(rankings)
    w = normalize_weights(weights or {}, pillars)
    ranks: dict[str, dict[str, int | None]] = {}
    for pillar, ranked in rankings.items():
        for position, doc_id in enumerate(dict.fromkeys(ranked), start=1):
            ranks.setdefault(doc_id, dict.fromkeys(pillars))[pillar] = position

    hits = []
    for doc_id, doc_ranks in ranks.items():
        contributions = {p: (w[p] / (k + r) if r is not None else 0.0) for p, r in doc_ranks.items()}
        hits.append((sum(contributions.values()), doc_id, doc_ranks, contributions))
    hits.sort(key=lambda h: (-h[0], min(r for r in h[2].values() if r is not None), h[1]))
    if top_k is not None:
        hits = hits[:top_k]
    return [
        FusedHit(doc_id, score, rank, doc_ranks, contributions)
        for rank, (score, doc_id, doc_ranks, contributions) in enumerate(hits, start=1)
    ]
