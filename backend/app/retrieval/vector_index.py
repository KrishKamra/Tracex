"""Pillar 2: exact cosine-similarity search over normalized dense embeddings.

With unit vectors, cosine similarity is a plain dot product, so exact
(brute-force) search is a single matrix-vector product. It is O(N d) per query
and exact, which suits evaluation: ANN recall loss never confounds an ablation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.nlp.embeddings import l2_normalize


@dataclass(frozen=True, slots=True)
class VectorHit:
    doc_id: str
    score: float
    rank: int


class VectorIndex:
    def __init__(self, doc_ids: Sequence[str], vectors: np.ndarray) -> None:
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or len(doc_ids) != vectors.shape[0]:
            raise ValueError("vectors must be a (len(doc_ids), d) matrix")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("doc_ids must be unique")
        self.doc_ids = list(doc_ids)
        self.vectors = l2_normalize(vectors)

    def __len__(self) -> int:
        return len(self.doc_ids)

    @property
    def dimension(self) -> int:
        return self.vectors.shape[1]

    def scores(self, query_vector: np.ndarray) -> np.ndarray:
        query = l2_normalize(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
        if query.shape[0] != self.dimension:
            raise ValueError(f"query has dimension {query.shape[0]}, index has {self.dimension}")
        return self.vectors @ query

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> list[VectorHit]:
        scores = self.scores(query_vector)
        indices = np.arange(len(scores))
        order = np.lexsort((indices, -scores))[:top_k]
        return [VectorHit(self.doc_ids[i], float(scores[i]), rank) for rank, i in enumerate(order, start=1)]
