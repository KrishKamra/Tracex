"""Pydantic v2 contracts for the Tracex REST API.

All models are strict (no type coercion) and reject unknown fields, so the
frontend contract cannot drift silently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SymbolKind = Literal["function", "method", "class"]
Language = Literal["python", "typescript", "tsx"]
Pillar = Literal["dense", "bm25", "graph"]


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


class ParsedQueryOut(StrictModel):
    raw: str
    text: str
    symbol: str | None
    route: str | None
    path: str | None


class SearchTimings(StrictModel):
    embedding_ms: float = 0.0
    dense_ms: float = 0.0
    bm25_ms: float = 0.0
    ast_graph_ms: float = 0.0
    rrf_ms: float = 0.0
    rerank_ms: float = 0.0
    filter_ms: float = 0.0
    total_ms: float = 0.0


class SearchHitOut(StrictModel):
    rank: int
    symbol_id: str
    qualified_name: str
    name: str
    kind: SymbolKind
    language: Language
    file_path: str
    start_line: int
    end_line: int
    signature: str
    summary: str = Field(description="First line of the docstring")
    snippet: str = Field(description="Leading source lines of the chunk")
    score: float = Field(description="Reranker probability if reranked, else the RRF score")
    rrf_score: float
    dense_rank: int | None
    bm25_rank: int | None
    graph_rank: int | None
    contributions: dict[str, float] = Field(description="Per-pillar RRF terms w_m / (k + r_m)")
    match_origin: list[str] = Field(
        description="Pillars that retrieved the hit, strongest first; or 'filter'"
    )
    matched_terms: list[str]
    rerank_score: float | None


class SearchResponse(StrictModel):
    query: ParsedQueryOut
    pillars: list[Pillar]
    reranked: bool
    candidates: int = Field(description="Symbols eligible after prefix filters")
    hits: list[SearchHitOut]
    timings: SearchTimings


# --------------------------------------------------------------------------- #
# Symbol inspector
# --------------------------------------------------------------------------- #


class ParameterOut(StrictModel):
    name: str
    annotation: str | None
    default: str | None


class ScopeTable(StrictModel):
    params: list[ParameterOut]
    locals: list[str]
    raises: list[str]
    returns: list[str]
    return_type: str | None


class ImportOut(StrictModel):
    module: str
    name: str | None
    alias: str | None
    line: int


class CallSiteOut(StrictModel):
    callee: str
    line: int
    target_id: str | None = Field(description="Resolved definition, if the call graph resolved it")


class Highlight(StrictModel):
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int


class FileSource(StrictModel):
    path: str
    language: Language
    line_count: int
    source: str


class SymbolDetail(StrictModel):
    symbol_id: str
    qualified_name: str
    name: str
    kind: SymbolKind
    language: Language
    file_path: str
    signature: str
    decorators: list[str]
    docstring: str
    parent_scope: str | None
    enclosing_class: str | None
    bases: list[str]
    routes: list[str]
    highlight: Highlight
    scope: ScopeTable
    imports: list[ImportOut]
    call_sites: list[CallSiteOut]
    fan_in: int
    fan_out: int
    file: FileSource


# --------------------------------------------------------------------------- #
# Call graph (shaped for @xyflow/react)
# --------------------------------------------------------------------------- #


class Position(StrictModel):
    x: float
    y: float


class GraphNodeData(StrictModel):
    symbol_id: str
    label: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    role: Literal["focus", "caller", "callee"]
    depth: int = Field(description="Negative upstream (callers), 0 focus, positive downstream")
    fan_in: int
    fan_out: int
    hidden_callers: int = Field(description="Callers not shown: render as a '+N callers' expander")
    hidden_callees: int = Field(description="Callees not shown: render as a '+N callees' expander")


class GraphNode(StrictModel):
    id: str
    type: Literal["symbol"] = "symbol"
    position: Position
    data: GraphNodeData


class GraphEdgeData(StrictModel):
    kind: Literal["CALLS", "INHERITS"]
    call_lines: list[int] = Field(description="Lines in the source node where the call happens")


class GraphEdge(StrictModel):
    id: str
    source: str
    target: str
    type: Literal["smoothstep"] = "smoothstep"
    animated: bool = False
    data: GraphEdgeData


class GraphResponse(StrictModel):
    focus: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    fan_in: int
    fan_out: int


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #


class IndexRequest(StrictModel):
    path: str = Field(min_length=1, description="Repository root to index")


class IndexResponse(StrictModel):
    repository: str
    files: int
    symbols: int
    nodes: int
    edges: dict[str, int]
    languages: dict[str, int]
    parse_errors: int
    call_resolution_rate: float
    embedding_model: str
    reranker_model: str | None
    device: str
    build_ms: dict[str, float]
    duration_ms: float
    parser_versions: dict[str, str]


class HealthResponse(StrictModel):
    status: Literal["ok"]
    indexed: bool
    version: str
