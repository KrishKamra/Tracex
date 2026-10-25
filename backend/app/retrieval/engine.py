"""Hybrid retrieval engine: BM25 + dense + call graph -> weighted RRF -> reranker.

```
query --+--> BM25 (sub-token)  ------------------+
        +--> E(q) . E(c_i) (dense) --------------+--> weighted RRF --> [cross-encoder] --> hits
        +--> RRF(dense, bm25) top seeds --> 1-hop graph expansion --+
```

Every stage is timed so the API can expose a latency breakdown, and every hit
carries its per-pillar ranks and RRF contributions for explainability.
"""

from __future__ import annotations

import os
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from app.nlp.embeddings import CodeEmbedder
from app.nlp.serializer import serialize_chunk
from app.nlp.tokenizer import CodeTokenizer
from app.parser.ast_engine import ASTEngine, SymbolNode
from app.retrieval.bm25_index import BM25Index
from app.retrieval.call_graph import CallGraph
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.rrf_fusion import DEFAULT_RRF_K, weighted_rrf
from app.retrieval.vector_index import VectorIndex

DEFAULT_WEIGHTS: Mapping[str, float] = {"dense": 0.4, "bm25": 0.4, "graph": 0.2}


@dataclass(frozen=True)
class SearchConfig:
    use_dense: bool = True
    use_bm25: bool = True
    use_graph: bool = True
    use_reranker: bool = False
    weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    candidate_k: int = 50  # per-pillar candidate depth fed into RRF
    seed_k: int = 10  # graph seeds S_0 taken from RRF(dense, bm25)
    rerank_k: int = 20  # fused candidates rescored by the cross-encoder
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        if not (self.use_dense or self.use_bm25):
            raise ValueError("at least one of the dense or BM25 pillars must be enabled")

    @property
    def pillars(self) -> tuple[str, ...]:
        enabled = {"dense": self.use_dense, "bm25": self.use_bm25, "graph": self.use_graph}
        return tuple(p for p, on in enabled.items() if on)


@dataclass(frozen=True)
class SearchHit:
    symbol: SymbolNode
    rank: int
    score: float
    rrf_score: float
    ranks: Mapping[str, int | None]
    contributions: Mapping[str, float]
    match_origin: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()
    rerank_score: float | None = None

    @property
    def symbol_id(self) -> str:
        return self.symbol.symbol_id


@dataclass(frozen=True)
class PillarRankings:
    """First-stage candidate lists; independent of fusion weights, so reusable across them."""

    query: str
    dense: list[str] | None
    bm25: list[str] | None
    matched_terms: Mapping[str, tuple[str, ...]]
    timings_ms: Mapping[str, float]
    elapsed_ms: float


@dataclass(frozen=True)
class SearchResult:
    query: str
    hits: list[SearchHit]
    timings_ms: Mapping[str, float]

    @property
    def ranked_ids(self) -> list[str]:
        return [h.symbol_id for h in self.hits]


class _Timer:
    def __init__(self) -> None:
        self.timings: dict[str, float] = {}

    def stage(self, name: str) -> _Stage:
        return _Stage(self, name)


class _Stage:
    def __init__(self, timer: _Timer, name: str) -> None:
        self.timer, self.name = timer, name

    def __enter__(self) -> None:
        self.start = time.perf_counter()

    def __exit__(self, *exc: object) -> None:
        elapsed = (time.perf_counter() - self.start) * 1000
        self.timer.timings[self.name] = self.timer.timings.get(self.name, 0.0) + elapsed


class HybridSearchEngine:
    def __init__(
        self,
        symbols: Iterable[SymbolNode],
        embedder: CodeEmbedder,
        *,
        reranker: CrossEncoderReranker | None = None,
        tokenizer: CodeTokenizer | None = None,
    ) -> None:
        self.symbols = list(symbols)
        self.by_id = {s.symbol_id: s for s in self.symbols}
        self.embedder = embedder
        self.reranker = reranker
        ids = [s.symbol_id for s in self.symbols]
        self.texts = {s.symbol_id: serialize_chunk(s, include_context=True) for s in self.symbols}
        timer = _Timer()
        with timer.stage("bm25_index_ms"):
            self.bm25 = BM25Index(tokenizer=tokenizer).build(ids, [self.texts[i] for i in ids])
        with timer.stage("embedding_index_ms"):
            self.vectors = VectorIndex(ids, embedder.encode([self.texts[i] for i in ids]))
        with timer.stage("graph_build_ms"):
            self.graph = CallGraph(self.symbols)
        self.build_timings_ms = timer.timings

    @classmethod
    def from_repository(
        cls,
        root: str | os.PathLike[str],
        embedder: CodeEmbedder,
        *,
        reranker: CrossEncoderReranker | None = None,
        ast_engine: ASTEngine | None = None,
    ) -> HybridSearchEngine:
        parsed = (ast_engine or ASTEngine()).parse_repository(root)
        return cls([s for f in parsed for s in f.symbols], embedder, reranker=reranker)

    def retrieve(
        self, query: str, config: SearchConfig | None = None, allowed: Collection[str] | None = None
    ) -> PillarRankings:
        """Run the weight-independent first stage: dense and BM25 candidate lists.

        ``allowed`` restricts candidates (prefix filters); rankings are then taken
        over the allowed subset, still capped at ``config.candidate_k``.
        """
        config = config or SearchConfig()
        timer = _Timer()
        start = time.perf_counter()
        depth = config.candidate_k if allowed is None else len(self.symbols)
        keep = (lambda doc_id: True) if allowed is None else set(allowed).__contains__
        dense = bm25 = None
        matched_terms: dict[str, tuple[str, ...]] = {}
        if config.use_dense:
            with timer.stage("embedding_ms"):
                query_vector = self.embedder.encode_query(query)
            with timer.stage("dense_ms"):
                hits = self.vectors.search(query_vector, depth)
                dense = [h.doc_id for h in hits if keep(h.doc_id)][: config.candidate_k]
        if config.use_bm25:
            with timer.stage("bm25_ms"):
                bm25_hits = [h for h in self.bm25.search(query, depth) if keep(h.doc_id)][
                    : config.candidate_k
                ]
                bm25 = [h.doc_id for h in bm25_hits]
                matched_terms = {h.doc_id: h.matched_terms for h in bm25_hits}
        elapsed = (time.perf_counter() - start) * 1000
        return PillarRankings(query, dense, bm25, matched_terms, timer.timings, elapsed)

    def fuse(
        self,
        pillars: PillarRankings,
        config: SearchConfig | None = None,
        top_k: int = 10,
        allowed: Collection[str] | None = None,
    ) -> SearchResult:
        """Second stage: graph expansion, weighted RRF and optional reranking."""
        config = config or SearchConfig()
        if config.use_reranker and self.reranker is None:
            raise ValueError("config.use_reranker is set but the engine has no reranker")
        timer = _Timer()
        start = time.perf_counter()
        rankings: dict[str, list[str]] = {}
        for name, ranked, enabled in (
            ("dense", pillars.dense, config.use_dense),
            ("bm25", pillars.bm25, config.use_bm25),
        ):
            if enabled:
                if ranked is None:
                    raise ValueError(f"config enables {name} but it was not retrieved")
                rankings[name] = ranked
        if config.use_graph:
            with timer.stage("ast_graph_ms"):
                seeds = weighted_rrf(dict(rankings), config.weights, k=config.rrf_k, top_k=config.seed_k)
                expansion = self.graph.expand({h.doc_id: h.rrf_score for h in seeds})
                if allowed is not None:
                    allowed_set = set(allowed)
                    expansion = {d: v for d, v in expansion.items() if d in allowed_set}
                ordered = sorted(expansion.items(), key=lambda kv: (-kv[1], kv[0]))
                rankings["graph"] = [doc_id for doc_id, _ in ordered[: config.candidate_k]]

        with timer.stage("rrf_ms"):
            fused = weighted_rrf(rankings, config.weights, k=config.rrf_k)

        rerank_scores: dict[str, float] = {}
        if config.use_reranker:
            with timer.stage("rerank_ms"):
                head, tail = fused[: config.rerank_k], fused[config.rerank_k :]
                reranked = self.reranker.rerank(
                    pillars.query, [(h.doc_id, self.texts[h.doc_id]) for h in head]
                )
                rerank_scores = dict(reranked)
                by_doc = {h.doc_id: h for h in head}
                fused = [by_doc[doc_id] for doc_id, _ in reranked] + tail

        hits = []
        for rank, fused_hit in enumerate(fused[:top_k], start=1):
            rerank_score = rerank_scores.get(fused_hit.doc_id)
            hits.append(
                SearchHit(
                    symbol=self.by_id[fused_hit.doc_id],
                    rank=rank,
                    score=rerank_score if rerank_score is not None else fused_hit.rrf_score,
                    rrf_score=fused_hit.rrf_score,
                    ranks=fused_hit.ranks,
                    contributions=fused_hit.contributions,
                    match_origin=fused_hit.match_origin,
                    matched_terms=pillars.matched_terms.get(fused_hit.doc_id, ()),
                    rerank_score=rerank_score,
                )
            )
        timings = {**pillars.timings_ms, **timer.timings}
        timings["total_ms"] = pillars.elapsed_ms + (time.perf_counter() - start) * 1000
        return SearchResult(pillars.query, hits, timings)

    def search(
        self,
        query: str,
        top_k: int = 10,
        config: SearchConfig | None = None,
        allowed: Collection[str] | None = None,
    ) -> SearchResult:
        config = config or SearchConfig()
        return self.fuse(self.retrieve(query, config, allowed), config, top_k, allowed)
