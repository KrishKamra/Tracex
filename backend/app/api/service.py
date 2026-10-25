"""Application service: owns the active index and answers API queries.

The index is immutable once built. Re-indexing builds a fresh engine and swaps
the reference under a lock, so concurrent searches always see a complete,
consistent index and never block on an indexing run.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from app.api import schemas
from app.api.query_parser import apply_filters, effective_routes, parse_query
from app.nlp.embeddings import CodeEmbedder
from app.parser.ast_engine import ASTEngine, ParsedFile, SymbolNode
from app.retrieval.engine import HybridSearchEngine, SearchConfig
from app.retrieval.reranker import CrossEncoderReranker

SNIPPET_LINES = 8
MAX_GRAPH_NODES_PER_SIDE = 40
LAYER_X, ROW_Y = 320.0, 110.0
_PARSER_PACKAGES = ("tree-sitter", "tree-sitter-python", "tree-sitter-typescript")


class NotIndexedError(RuntimeError):
    pass


class SymbolNotFoundError(KeyError):
    pass


class IndexPathError(ValueError):
    pass


@dataclass(frozen=True)
class _Index:
    root: Path
    engine: HybridSearchEngine
    files: dict[str, ParsedFile]
    sources: dict[str, str]
    by_qualified: dict[tuple[str, str], SymbolNode]
    summary: schemas.IndexResponse


def _package_versions() -> dict[str, str]:
    versions = {}
    for package in _PARSER_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "unknown"
    return versions


class TracexService:
    def __init__(
        self,
        embedder_factory: Callable[[], CodeEmbedder],
        reranker_factory: Callable[[], CrossEncoderReranker | None] = lambda: None,
        *,
        workspace_root: str | os.PathLike[str] | None = None,
    ) -> None:
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._embedder: CodeEmbedder | None = None
        self._reranker: CrossEncoderReranker | None = None
        self._models_loaded = False
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self._index: _Index | None = None
        self._lock = threading.Lock()

    # -- indexing ----------------------------------------------------------- #
    @property
    def indexed(self) -> bool:
        return self._index is not None

    def _require_index(self) -> _Index:
        index = self._index
        if index is None:
            raise NotIndexedError("no repository is indexed yet; POST /api/v1/index first")
        return index

    def _resolve_root(self, path: str) -> Path:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise IndexPathError(f"not a directory: {path}")
        if self.workspace_root is not None and not root.is_relative_to(self.workspace_root):
            raise IndexPathError(f"{root} is outside the allowed workspace {self.workspace_root}")
        return root

    def index_repository(self, path: str) -> schemas.IndexResponse:
        root = self._resolve_root(path)
        with self._lock:
            start = time.perf_counter()
            if not self._models_loaded:
                self._embedder, self._reranker = self._embedder_factory(), self._reranker_factory()
                if self._reranker is not None:
                    self._reranker.warm_up()  # so the first rerank request is not a cold start
                self._models_loaded = True
            assert self._embedder is not None
            parsed = ASTEngine().parse_repository(root)
            symbols = [s for f in parsed for s in f.symbols]
            engine = HybridSearchEngine(symbols, self._embedder, reranker=self._reranker)
            files = {f.file_path: f for f in parsed}
            sources = {
                f.file_path: (root / f.file_path)
                .read_bytes()
                .decode("utf-8", errors="replace")
                .replace("\r\n", "\n")
                for f in parsed
            }
            stats = engine.graph.stats
            summary = schemas.IndexResponse(
                repository=str(root),
                files=len(parsed),
                symbols=len(symbols),
                nodes=engine.graph.graph.number_of_nodes(),
                edges=dict(stats.edges),
                languages=dict(sorted(Counter(f.language for f in parsed).items())),
                parse_errors=sum(f.has_error for f in parsed),
                call_resolution_rate=stats.resolution_rate,
                embedding_model=self._embedder.model_name,
                reranker_model=self._reranker.model_name if self._reranker else None,
                device=self._embedder.device,
                build_ms={k: round(v, 3) for k, v in engine.build_timings_ms.items()},
                duration_ms=round((time.perf_counter() - start) * 1000, 3),
                parser_versions=_package_versions(),
            )
            by_qualified = {(s.file_path, s.qualified_name): s for s in symbols}
            self._index = _Index(root, engine, files, sources, by_qualified, summary)
            return summary

    def index_status(self) -> schemas.IndexResponse:
        return self._require_index().summary

    # -- search ------------------------------------------------------------- #
    def search(
        self, q: str, *, dense: bool, bm25: bool, graph: bool, rerank: bool, top_k: int
    ) -> schemas.SearchResponse:
        index = self._require_index()
        engine = index.engine
        parsed = parse_query(q)
        config = SearchConfig(use_dense=dense, use_bm25=bm25, use_graph=graph, use_reranker=rerank)
        if rerank and engine.reranker is None:
            raise ValueError("reranking was requested but the server has no reranker loaded")

        start = time.perf_counter()
        allowed = apply_filters(parsed, engine.symbols) if parsed.has_filters else None
        filter_ms = (time.perf_counter() - start) * 1000
        candidates = len(allowed) if allowed is not None else len(engine.symbols)

        if parsed.text:
            allowed_ids = [s.symbol_id for s in allowed] if allowed is not None else None
            result = engine.search(parsed.text, top_k=top_k, config=config, allowed=allowed_ids)
            hits = [
                self._hit(
                    index,
                    h.symbol,
                    h.rank,
                    h.score,
                    h.rrf_score,
                    h.ranks,
                    h.contributions,
                    list(h.match_origin),
                    list(h.matched_terms),
                    h.rerank_score,
                )
                for h in result.hits
            ]
            timings = dict(result.timings_ms)
        else:  # filter-only query: order by filter match quality
            hits = [
                self._hit(index, s, rank, 1.0, 0.0, {}, {}, ["filter"], [], None)
                for rank, s in enumerate((allowed or [])[:top_k], start=1)
            ]
            timings = {}
        timings["filter_ms"] = filter_ms
        timings["total_ms"] = timings.get("total_ms", 0.0) + filter_ms
        return schemas.SearchResponse(
            query=schemas.ParsedQueryOut(
                raw=parsed.raw, text=parsed.text, symbol=parsed.symbol, route=parsed.route, path=parsed.path
            ),
            pillars=list(config.pillars) if parsed.text else [],
            reranked=bool(parsed.text and rerank),
            candidates=candidates,
            hits=hits,
            timings=schemas.SearchTimings(**{k: round(v, 3) for k, v in timings.items()}),
        )

    def _hit(self, index, symbol, rank, score, rrf_score, ranks, contributions, origin, terms, rerank_score):
        lines = index.sources[symbol.file_path].split("\n")
        snippet_end = min(symbol.end_line, symbol.start_line + SNIPPET_LINES - 1)
        return schemas.SearchHitOut(
            rank=rank,
            symbol_id=symbol.symbol_id,
            qualified_name=symbol.qualified_name,
            name=symbol.name,
            kind=symbol.kind,
            language=symbol.language,
            file_path=symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            signature=symbol.signature,
            summary=symbol.docstring.split("\n", 1)[0],
            snippet="\n".join(lines[symbol.start_line - 1 : snippet_end]),
            score=float(score),
            rrf_score=float(rrf_score),
            dense_rank=ranks.get("dense"),
            bm25_rank=ranks.get("bm25"),
            graph_rank=ranks.get("graph"),
            contributions={k: float(v) for k, v in contributions.items()},
            match_origin=origin,
            matched_terms=terms,
            rerank_score=float(rerank_score) if rerank_score is not None else None,
        )

    # -- symbol inspector --------------------------------------------------- #
    def _symbol(self, index: _Index, symbol_id: str) -> SymbolNode:
        symbol = index.engine.by_id.get(symbol_id)
        if symbol is None:
            raise SymbolNotFoundError(symbol_id)
        return symbol

    def symbol_detail(self, symbol_id: str) -> schemas.SymbolDetail:
        index = self._require_index()
        symbol = self._symbol(index, symbol_id)
        graph = index.engine.graph
        details = symbol.ast_scope_details
        parsed_file = index.files[symbol.file_path]
        source = index.sources[symbol.file_path]
        return schemas.SymbolDetail(
            symbol_id=symbol.symbol_id,
            qualified_name=symbol.qualified_name,
            name=symbol.name,
            kind=symbol.kind,
            language=symbol.language,
            file_path=symbol.file_path,
            signature=symbol.signature,
            decorators=list(symbol.decorators),
            docstring=symbol.docstring,
            parent_scope=symbol.parent_scope,
            enclosing_class=symbol.enclosing_class,
            bases=list(symbol.bases),
            routes=effective_routes(symbol, index.by_qualified),
            highlight=schemas.Highlight(
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                start_byte=symbol.start_byte,
                end_byte=symbol.end_byte,
            ),
            scope=schemas.ScopeTable(
                params=[
                    schemas.ParameterOut(name=p.name, annotation=p.annotation, default=p.default)
                    for p in details.params
                ],
                locals=list(details.locals),
                raises=list(details.raises),
                returns=list(details.returns),
                return_type=details.return_type,
            ),
            imports=[
                schemas.ImportOut(module=i.module, name=i.name, alias=i.alias, line=i.line)
                for i in parsed_file.imports
            ],
            call_sites=[
                schemas.CallSiteOut(
                    callee=site.callee,
                    line=site.line,
                    target_id=graph.resolve(symbol_id, site.callee),
                )
                for site in symbol.call_sites
            ],
            fan_in=graph.fan_in(symbol_id),
            fan_out=graph.fan_out(symbol_id),
            file=schemas.FileSource(
                path=symbol.file_path,
                language=parsed_file.language,
                line_count=parsed_file.line_count,
                source=source,
            ),
        )

    # -- call graph --------------------------------------------------------- #
    def call_graph(self, symbol_id: str, depth: int) -> schemas.GraphResponse:
        index = self._require_index()
        focus = self._symbol(index, symbol_id)
        graph = index.engine.graph

        levels: dict[str, int] = {focus.symbol_id: 0}
        for direction, step in ((-1, graph.callers), (1, graph.callees)):
            frontier = deque([(focus.symbol_id, 0)])
            seen_side = 0
            while frontier:
                node, level = frontier.popleft()
                if abs(level) >= depth:
                    continue
                for neighbour in step(node):
                    if neighbour in levels or seen_side >= MAX_GRAPH_NODES_PER_SIDE:
                        continue
                    levels[neighbour] = level + direction
                    seen_side += 1
                    frontier.append((neighbour, level + direction))

        layers: dict[int, list[str]] = {}
        for node, level in levels.items():
            layers.setdefault(level, []).append(node)
        positions: dict[str, schemas.Position] = {}
        for level, members in layers.items():
            members.sort(key=lambda n: index.engine.by_id[n].qualified_name)
            for row, node in enumerate(members):
                positions[node] = schemas.Position(
                    x=level * LAYER_X, y=(row - (len(members) - 1) / 2) * ROW_Y
                )

        included = set(levels)
        nodes = []
        for node_id in sorted(levels, key=lambda n: (levels[n], positions[n].y)):
            symbol = index.engine.by_id[node_id]
            level = levels[node_id]
            nodes.append(
                schemas.GraphNode(
                    id=node_id,
                    position=positions[node_id],
                    data=schemas.GraphNodeData(
                        symbol_id=node_id,
                        label=symbol.name,
                        qualified_name=symbol.qualified_name,
                        kind=symbol.kind,
                        file_path=symbol.file_path,
                        start_line=symbol.start_line,
                        role="focus" if level == 0 else ("caller" if level < 0 else "callee"),
                        depth=level,
                        fan_in=graph.fan_in(node_id),
                        fan_out=graph.fan_out(node_id),
                        hidden_callers=len(set(graph.callers(node_id)) - included),
                        hidden_callees=len(set(graph.callees(node_id)) - included),
                    ),
                )
            )
        edges = []
        for source, target, kind in sorted(graph.graph.edges(keys=True)):
            if kind in ("CALLS", "INHERITS") and source in included and target in included:
                edges.append(
                    schemas.GraphEdge(
                        id=f"{kind}:{source}->{target}",
                        source=source,
                        target=target,
                        data=schemas.GraphEdgeData(kind=kind, call_lines=graph.call_lines(source, target)),
                    )
                )
        return schemas.GraphResponse(
            focus=focus.symbol_id,
            depth=depth,
            nodes=nodes,
            edges=edges,
            fan_in=graph.fan_in(focus.symbol_id),
            fan_out=graph.fan_out(focus.symbol_id),
        )
