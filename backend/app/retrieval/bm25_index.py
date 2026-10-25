"""Pillar 1: sub-token aware Okapi BM25 over serialized AST chunks.

For query terms Q = {q_1..q_m} and chunk D:

    Score(D, Q) = sum_i IDF(q_i) * f(q_i, D) * (k1 + 1)
                  / (f(q_i, D) + k1 * (1 - b + b * |D| / avgdl))

    IDF(q) = ln(1 + (N - n(q) + 0.5) / (n(q) + 0.5))

with code-tuned k1 = 1.2, b = 0.75. The "+1" (Lucene) IDF variant keeps IDF
strictly positive, so a term that appears in most chunks can never *penalize*
a match. Query terms are deduplicated: identifier expansion already emits a
compound and its parts (``check_limit`` -> ``check_limit, check, limit``), and
counting a repeated part twice would over-weight it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.nlp.tokenizer import CodeTokenizer


@dataclass(frozen=True, slots=True)
class BM25Hit:
    doc_id: str
    score: float
    rank: int
    matched_terms: tuple[str, ...]


class BM25Index:
    def __init__(self, *, k1: float = 1.2, b: float = 0.75, tokenizer: CodeTokenizer | None = None) -> None:
        self.k1 = k1
        self.b = b
        self.tokenizer = tokenizer or CodeTokenizer()
        self.doc_ids: list[str] = []
        self.doc_lengths = np.zeros(0, dtype=np.float64)
        self.avgdl = 0.0
        # term -> (document indices, term frequencies)
        self._postings: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._idf: dict[str, float] = {}
        self._doc_terms: list[frozenset[str]] = []

    def __len__(self) -> int:
        return len(self.doc_ids)

    def build(self, doc_ids: Sequence[str], texts: Sequence[str]) -> BM25Index:
        if len(doc_ids) != len(texts):
            raise ValueError("doc_ids and texts must have the same length")
        if len(set(doc_ids)) != len(doc_ids):
            raise ValueError("doc_ids must be unique")
        self.doc_ids = list(doc_ids)
        postings: dict[str, tuple[list[int], list[int]]] = {}
        lengths = []
        self._doc_terms = []
        for index, text in enumerate(texts):
            counts = Counter(self.tokenizer.tokenize(text))
            lengths.append(sum(counts.values()))
            self._doc_terms.append(frozenset(counts))
            for term, tf in counts.items():
                docs, tfs = postings.setdefault(term, ([], []))
                docs.append(index)
                tfs.append(tf)
        self.doc_lengths = np.asarray(lengths, dtype=np.float64)
        self.avgdl = float(self.doc_lengths.mean()) if lengths else 0.0
        n_docs = len(self.doc_ids)
        self._postings = {
            term: (np.asarray(docs, dtype=np.int64), np.asarray(tfs, dtype=np.float64))
            for term, (docs, tfs) in postings.items()
        }
        self._idf = {
            term: math.log(1 + (n_docs - len(docs) + 0.5) / (len(docs) + 0.5))
            for term, (docs, _) in postings.items()
        }
        return self

    def idf(self, term: str) -> float:
        return self._idf.get(term, 0.0)

    def query_terms(self, query: str) -> list[str]:
        return list(dict.fromkeys(self.tokenizer.tokenize(query)))

    def scores(self, query: str) -> np.ndarray:
        """BM25 score of every document (dense vector aligned with ``doc_ids``)."""
        scores = np.zeros(len(self.doc_ids), dtype=np.float64)
        if not self.doc_ids or self.avgdl == 0:
            return scores
        norm = self.k1 * (1 - self.b + self.b * self.doc_lengths / self.avgdl)
        for term in self.query_terms(query):
            posting = self._postings.get(term)
            if posting is None:
                continue
            docs, tfs = posting
            scores[docs] += self._idf[term] * tfs * (self.k1 + 1) / (tfs + norm[docs])
        return scores

    def search(self, query: str, top_k: int = 10) -> list[BM25Hit]:
        """Top-k documents with a positive score, ties broken by index order."""
        scores = self.scores(query)
        candidates = np.flatnonzero(scores > 0)
        order = candidates[np.lexsort((candidates, -scores[candidates]))][:top_k]
        terms = self.query_terms(query)
        hits = []
        for rank, index in enumerate(order, start=1):
            matched = tuple(t for t in terms if t in self._doc_terms[index])
            hits.append(BM25Hit(self.doc_ids[index], float(scores[index]), rank, matched))
        return hits
