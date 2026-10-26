// Mirrors backend/app/api/schemas.py. Keep the two in sync: the backend models
// are strict (extra="forbid"), so a drifted field fails loudly in tests.

export type SymbolKind = "function" | "method" | "class";
export type Language = "python" | "typescript" | "tsx";
export type Pillar = "dense" | "bm25" | "graph";

export interface ParsedQuery {
  raw: string;
  text: string;
  symbol: string | null;
  route: string | null;
  path: string | null;
}

export interface SearchTimings {
  embedding_ms: number;
  dense_ms: number;
  bm25_ms: number;
  ast_graph_ms: number;
  rrf_ms: number;
  rerank_ms: number;
  filter_ms: number;
  total_ms: number;
}

export interface SearchHit {
  rank: number;
  symbol_id: string;
  qualified_name: string;
  name: string;
  kind: SymbolKind;
  language: Language;
  file_path: string;
  start_line: number;
  end_line: number;
  signature: string;
  summary: string;
  snippet: string;
  score: number;
  rrf_score: number;
  dense_rank: number | null;
  bm25_rank: number | null;
  graph_rank: number | null;
  contributions: Partial<Record<Pillar, number>>;
  match_origin: string[];
  matched_terms: string[];
  rerank_score: number | null;
}

export interface SearchResponse {
  query: ParsedQuery;
  pillars: Pillar[];
  reranked: boolean;
  candidates: number;
  hits: SearchHit[];
  timings: SearchTimings;
}

export interface Parameter {
  name: string;
  annotation: string | null;
  default: string | null;
}

export interface ScopeTable {
  params: Parameter[];
  locals: string[];
  raises: string[];
  returns: string[];
  return_type: string | null;
}

export interface ImportRef {
  module: string;
  name: string | null;
  alias: string | null;
  line: number;
}

export interface CallSite {
  callee: string;
  line: number;
  target_id: string | null;
}

export interface SymbolDetail {
  symbol_id: string;
  qualified_name: string;
  name: string;
  kind: SymbolKind;
  language: Language;
  file_path: string;
  signature: string;
  decorators: string[];
  docstring: string;
  parent_scope: string | null;
  enclosing_class: string | null;
  bases: string[];
  routes: string[];
  highlight: { start_line: number; end_line: number; start_byte: number; end_byte: number };
  scope: ScopeTable;
  imports: ImportRef[];
  call_sites: CallSite[];
  fan_in: number;
  fan_out: number;
  file: { path: string; language: Language; line_count: number; source: string };
}

export type GraphRole = "focus" | "caller" | "callee";

export interface GraphNodeData {
  symbol_id: string;
  label: string;
  qualified_name: string;
  kind: SymbolKind;
  file_path: string;
  start_line: number;
  role: GraphRole;
  depth: number;
  fan_in: number;
  fan_out: number;
  hidden_callers: number;
  hidden_callees: number;
}

export interface GraphNodeOut {
  id: string;
  type: "symbol";
  position: { x: number; y: number };
  data: GraphNodeData;
}

export interface GraphEdgeOut {
  id: string;
  source: string;
  target: string;
  type: "smoothstep";
  animated: boolean;
  data: { kind: "CALLS" | "INHERITS"; call_lines: number[] };
}

export interface GraphResponse {
  focus: string;
  depth: number;
  nodes: GraphNodeOut[];
  edges: GraphEdgeOut[];
  fan_in: number;
  fan_out: number;
}

export interface IndexSummary {
  repository: string;
  files: number;
  symbols: number;
  nodes: number;
  edges: Record<string, number>;
  languages: Record<string, number>;
  parse_errors: number;
  call_resolution_rate: number;
  embedding_model: string;
  reranker_model: string | null;
  device: string;
  build_ms: Record<string, number>;
  duration_ms: number;
  parser_versions: Record<string, string>;
}

export interface Health {
  status: "ok";
  indexed: boolean;
  version: string;
}
