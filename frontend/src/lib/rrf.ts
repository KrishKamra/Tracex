import type { Pillar, SearchHit } from "./types";

export const PILLARS: { key: Pillar; name: string; short: string; desc: string; color: string }[] = [
  { key: "dense", name: "Dense Vector", short: "Dense", desc: "Embedding similarity over code + docstrings", color: "var(--mint)" },
  { key: "bm25", name: "BM25 Keyword", short: "BM25", desc: "Lexical match on identifier sub-tokens", color: "var(--trace)" },
  { key: "graph", name: "AST Graph Expansion", short: "Graph", desc: "Expand top seeds 1 hop along call edges", color: "var(--violet)" },
];

export type Origin = "Exact" | "Keyword" | "Semantic" | "Call Graph" | "Filter";

/** Mirror of backend split_identifier: snake_case, camelCase, PascalCase and digit boundaries. */
export function splitIdentifier(identifier: string): string[] {
  return identifier
    .split(/[_$]+/)
    .flatMap((part) => part.match(/[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+/g) ?? [])
    .map((p) => p.toLowerCase());
}

/** BM25 matched the identifier itself, or every one of its sub-tokens. */
export function isExactMatch(hit: SearchHit): boolean {
  const terms = new Set(hit.matched_terms);
  const parts = splitIdentifier(hit.name);
  return terms.has(hit.name.toLowerCase()) || (parts.length > 0 && parts.every((p) => terms.has(p)));
}

/** Badge label: the pillar contributing most, with exact-identifier BM25 matches called out. */
export function originLabel(hit: SearchHit): Origin {
  const top = hit.match_origin[0];
  if (top === "filter") return "Filter";
  if (top === "graph") return "Call Graph";
  if (top === "bm25") return isExactMatch(hit) ? "Exact" : "Keyword";
  return "Semantic";
}

export const ORIGIN_TONE: Record<Origin, string> = {
  Semantic: "mint",
  Keyword: "trace",
  Exact: "trace",
  "Call Graph": "violet",
  Filter: "sub",
};

export interface Contribution {
  pillar: Pillar;
  rank: number | null;
  value: number;
  share: number; // fraction of the fused RRF score, 0..1
}

/** Per-pillar terms w_m / (k + r_m) and their share of the fused score. */
export function contributionBreakdown(hit: SearchHit): Contribution[] {
  const ranks: Record<Pillar, number | null> = { dense: hit.dense_rank, bm25: hit.bm25_rank, graph: hit.graph_rank };
  const total = Object.values(hit.contributions).reduce((a, b) => a + (b ?? 0), 0);
  return PILLARS.map(({ key }) => {
    const value = hit.contributions[key] ?? 0;
    return { pillar: key, rank: ranks[key], value, share: total > 0 ? value / total : 0 };
  });
}

/** Human-readable justification for why a hit matched. */
export function justification(hit: SearchHit): string[] {
  const reasons: string[] = [];
  if (hit.match_origin[0] === "filter") return ["Matched the prefix filter"];
  if (hit.dense_rank) reasons.push(`Ranked #${hit.dense_rank} by embedding similarity`);
  if (hit.bm25_rank) {
    const terms = hit.matched_terms.slice(0, 6).join(", ");
    reasons.push(`Ranked #${hit.bm25_rank} by BM25${terms ? ` on ${terms}` : ""}`);
  }
  if (hit.graph_rank) reasons.push(`Ranked #${hit.graph_rank} as a call-graph neighbour of top results`);
  if (hit.rerank_score !== null) reasons.push(`Cross-encoder relevance ${(hit.rerank_score * 100).toFixed(0)}%`);
  return reasons;
}
