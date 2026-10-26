import type { GraphResponse, Health, IndexSummary, SearchResponse, SymbolDetail } from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface SearchOptions {
  dense: boolean;
  bm25: boolean;
  graph: boolean;
  rerank: boolean;
  topK?: number;
}

export function searchUrl(q: string, o: SearchOptions): string {
  const params = new URLSearchParams({
    q,
    dense: String(o.dense),
    bm25: String(o.bm25),
    graph: String(o.graph),
    rerank: String(o.rerank),
    top_k: String(o.topK ?? 20),
  });
  return `${BASE}/search?${params}`;
}

/** Symbol ids contain "/" and "::"; keep slashes (the route is `{id:path}`), encode the rest. */
export function encodeSymbolId(id: string): string {
  return id.split("/").map(encodeURIComponent).join("/");
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { Accept: "application/json", ...init?.headers } });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>(`${BASE}/health`, { signal }),
  index: (signal?: AbortSignal) => request<IndexSummary>(`${BASE}/index`, { signal }),
  reindex: (path: string) =>
    request<IndexSummary>(`${BASE}/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }),
  search: (q: string, o: SearchOptions, signal?: AbortSignal) => request<SearchResponse>(searchUrl(q, o), { signal }),
  symbol: (id: string, signal?: AbortSignal) =>
    request<SymbolDetail>(`${BASE}/symbol/${encodeSymbolId(id)}`, { signal }),
  graph: (id: string, depth = 1, signal?: AbortSignal) =>
    request<GraphResponse>(`${BASE}/graph/${encodeSymbolId(id)}?depth=${depth}`, { signal }),
};

export type Api = typeof api;
