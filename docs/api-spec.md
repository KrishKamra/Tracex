# API specification

REST API served by `backend/app/api` (FastAPI). Version **0.3.0**, base path `/api/v1`.
Interactive docs live at `/docs` and the OpenAPI schema at `/openapi.json`.

> [!NOTE]
> Every model is a **strict** Pydantic v2 model: no type coercion, unknown fields
> rejected (`extra="forbid"`). The frontend mirrors them in
> [`frontend/src/lib/types.ts`](../frontend/src/lib/types.ts), and its tests run
> against payloads captured from this API, so contract drift fails CI.

| Method | Path | Purpose |
|---|---|---|
| `GET` | [`/health`](#get-health) | Liveness and index state |
| `POST` | [`/index`](#post-index) | Index (or re-index) a repository |
| `GET` | [`/index`](#get-index) | Summary of the current index |
| `GET` | [`/search`](#get-search) | Hybrid search with explainable ranks |
| `GET` | [`/symbol/{symbol_id}`](#get-symbolsymbol_id) | Source, scope table and resolved call sites |
| `GET` | [`/graph/{symbol_id}`](#get-graphsymbol_id) | Call-graph ego network for `@xyflow/react` |

## Conventions

* **Symbol ids** look like `billing/payments.py::charge_customer`. They contain `/`, which
  the path parameters accept (`{symbol_id:path}`). Percent-encode everything except `/`.
* **Errors** use FastAPI's envelope, `{"detail": …}`. A 422 carries the list of
  validation errors.
* **Telemetry.** Every response sets `X-Response-Time-Ms` and `Server-Timing`. Search
  responses add one `Server-Timing` entry per pipeline stage, so browser devtools show
  the breakdown natively.

| Status | Meaning |
|---|---|
| 400 | Invalid index path (missing, not a directory, outside `TRACEX_WORKSPACE_ROOT`), or `rerank=true` with no reranker loaded |
| 404 | Unknown `symbol_id` |
| 409 | No repository indexed yet |
| 422 | Schema violation: `top_k=0`, `depth=4`, `dense` and `bm25` both off, wrong body types, extra fields |

---

## `GET /health`

```json
{ "status": "ok", "indexed": true, "version": "0.3.0" }
```

## `POST /index`

Parses, embeds and graphs a repository, then atomically swaps it in. The call is synchronous;
embedding dominates (≈ 0.3 s per chunk on CPU).

| Body field | Type | Notes |
|---|---|---|
| `path` | string, non-empty | Directory to index. Must lie inside `TRACEX_WORKSPACE_ROOT` when that is set. |

```bash
curl -X POST localhost:8000/api/v1/index -H 'content-type: application/json' \
     -d '{"path": "/repos/billing_service"}'
```

```json
{
  "repository": "/repos/billing_service",
  "files": 13,
  "symbols": 65,
  "nodes": 77,
  "edges": { "CALLS": 51, "IMPORTS": 17 },
  "languages": { "python": 8, "tsx": 1, "typescript": 4 },
  "parse_errors": 0,
  "call_resolution_rate": 0.3643,
  "embedding_model": "jinaai/jina-embeddings-v2-base-code",
  "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "device": "cpu",
  "build_ms": { "bm25_index_ms": 6.181, "embedding_index_ms": 19925.301, "graph_build_ms": 1.827 },
  "duration_ms": 39773.398,
  "parser_versions": { "tree-sitter": "0.26.0", "tree-sitter-python": "0.25.0", "tree-sitter-typescript": "0.23.2" }
}
```

## `GET /index`

Returns the same `IndexResponse` for the current index, or 409 if nothing is indexed.

## `GET /search`

| Query param | Type | Default | Notes |
|---|---|---|---|
| `q` | string, 1–500 chars | required | Free text plus optional prefixes (below) |
| `dense` | bool | `true` | Dense pillar |
| `bm25` | bool | `true` | BM25 pillar (at least one of `dense` / `bm25` is required) |
| `graph` | bool | `true` | Graph expansion pillar (seeded by dense + BM25) |
| `rerank` | bool | `false` | Cross-encoder over the fused top-20 (needs `TRACEX_RERANKER=1`) |
| `top_k` | int, 1–100 | `10` | Hits returned |

**Prefixes.** All prefixes are ANDed together. The remaining words are ranked within the filtered set.

| Prefix | Matches | Example |
|---|---|---|
| `@name` | Symbol name / qualified name. Ordered exact → prefix → suffix → substring. | `@save` |
| `#route` | Effective route: class decorator prefix joined with method route | `#/webhooks/stripe` |
| `/path` | File path, anchored at a segment boundary (`/hooks` ≠ `webhooks.py`) | `/billing/ refund` |

A filter-only query (`@check_limit`) returns matches ordered by filter quality, with
`match_origin: ["filter"]` and `pillars: []`.

```bash
curl 'localhost:8000/api/v1/search?q=check%20spending%20limit&top_k=5'
```

```json
{
  "query": { "raw": "check spending limit", "text": "check spending limit", "symbol": null, "route": null, "path": null },
  "pillars": ["dense", "bm25", "graph"],
  "reranked": false,
  "candidates": 65,
  "hits": [
    {
      "rank": 1,
      "symbol_id": "billing/limits.py::check_limit",
      "qualified_name": "check_limit",
      "name": "check_limit",
      "kind": "function",
      "language": "python",
      "file_path": "billing/limits.py",
      "start_line": 27,
      "end_line": 34,
      "signature": "def check_limit(account_id: str, amount: int, tier: str = \"standard\", policy: SpendingPolicy | None = None) -> bool",
      "summary": "Return True if charging `amount` keeps the account within its monthly budget.",
      "snippet": "def check_limit(\n    account_id: str, amount: int, …",
      "score": 0.01639,
      "rrf_score": 0.01639,
      "dense_rank": 1,
      "bm25_rank": 1,
      "graph_rank": 1,
      "contributions": { "dense": 0.006557, "bm25": 0.006557, "graph": 0.003279 },
      "match_origin": ["bm25", "dense", "graph"],
      "matched_terms": ["check", "spending", "limit"],
      "rerank_score": null
    }
  ],
  "timings": {
    "embedding_ms": 87.006, "dense_ms": 0.404, "bm25_ms": 0.459, "ast_graph_ms": 1.013,
    "rrf_ms": 0.745, "rerank_ms": 0.0, "filter_ms": 0.004, "total_ms": 89.739
  }
}
```

```http
Server-Timing: embedding;dur=87.006, dense;dur=0.404, bm25;dur=0.459, ast_graph;dur=1.013, rrf;dur=0.745, filter;dur=0.004, total;dur=89.739, app;dur=94.046
X-Response-Time-Ms: 94.046
```

| Hit field | Meaning |
|---|---|
| `score` | Reranker probability when reranked, else `rrf_score` |
| `rrf_score` | $\sum_m w_m/(60 + r_m)$ over active pillars |
| `dense_rank` · `bm25_rank` · `graph_rank` | 1-based rank in each pillar; `null` if that pillar did not retrieve it |
| `contributions` | Per-pillar RRF terms (they sum to `rrf_score`) |
| `match_origin` | Pillars that retrieved the hit, strongest contribution first; or `["filter"]` |
| `matched_terms` | BM25 query terms (after sub-tokenization) present in the chunk |
| `summary` · `snippet` | First docstring line · first 8 source lines of the chunk |

## `GET /symbol/{symbol_id}`

```bash
curl localhost:8000/api/v1/symbol/billing/payments.py::charge_customer
```

```json
{
  "symbol_id": "billing/payments.py::charge_customer",
  "qualified_name": "charge_customer",
  "kind": "function",
  "language": "python",
  "file_path": "billing/payments.py",
  "signature": "def charge_customer(gateway: PaymentGateway, customer: dict, amount: int) -> dict",
  "decorators": [],
  "docstring": "Charge a customer after enforcing their spending limit, then persist and email a receipt.",
  "parent_scope": null,
  "enclosing_class": null,
  "bases": [],
  "routes": [],
  "highlight": { "start_line": 44, "end_line": 53, "start_byte": 1486, "end_byte": 2152 },
  "scope": {
    "params": [
      { "name": "gateway", "annotation": "PaymentGateway", "default": null },
      { "name": "customer", "annotation": "dict", "default": null },
      { "name": "amount", "annotation": "int", "default": null }
    ],
    "locals": ["charge", "payment"],
    "raises": ["LimitExceededError"],
    "returns": ["payment"],
    "return_type": "dict"
  },
  "imports": [{ "module": ".limits", "name": "check_limit", "alias": null, "line": 5 }],
  "call_sites": [
    { "callee": "check_limit", "line": 46, "target_id": "billing/limits.py::check_limit" },
    { "callee": "customer.get", "line": 46, "target_id": null },
    { "callee": "LimitExceededError", "line": 47, "target_id": "billing/payments.py::LimitExceededError" }
  ],
  "fan_in": 0,
  "fan_out": 8,
  "file": { "path": "billing/payments.py", "language": "python", "line_count": 66, "source": "…full file…" }
}
```

* `call_sites` resolve **independently**, even when two calls share a line, as on
  line 46 above. `target_id: null` means a builtin, third-party or untyped call.
* `routes` joins class and method route decorators: `@Controller("/webhooks")` +
  `@Post("/stripe")` gives `/webhooks/stripe`.

## `GET /graph/{symbol_id}`

| Query param | Type | Default | Notes |
|---|---|---|---|
| `depth` | int, 1–3 | `1` | Hops upstream (callers) and downstream (callees) |

Returns an ego network shaped for `@xyflow/react`. Each side is capped at 40 nodes.

```json
{
  "focus": "billing/limits.py::check_limit",
  "depth": 1,
  "nodes": [
    {
      "id": "billing/payments.py::charge_customer",
      "type": "symbol",
      "position": { "x": -320.0, "y": 0.0 },
      "data": {
        "symbol_id": "billing/payments.py::charge_customer",
        "label": "charge_customer",
        "qualified_name": "charge_customer",
        "kind": "function",
        "file_path": "billing/payments.py",
        "start_line": 44,
        "role": "caller",
        "depth": -1,
        "fan_in": 0,
        "fan_out": 8,
        "hidden_callers": 0,
        "hidden_callees": 7
      }
    }
  ],
  "edges": [
    {
      "id": "CALLS:billing/limits.py::check_limit->billing/limits.py::SpendingPolicy",
      "source": "billing/limits.py::check_limit",
      "target": "billing/limits.py::SpendingPolicy",
      "type": "smoothstep",
      "animated": false,
      "data": { "kind": "CALLS", "call_lines": [31] }
    }
  ],
  "fan_in": 1,
  "fan_out": 3
}
```

* `hidden_callers` / `hidden_callees` drive the "+N" expanders. The client merges the
  neighbour's own ego network on demand.
* `call_lines` are lines **in the source node** where the call happens; trace mode
  highlights them.
* `position` is a horizontal layering hint (`x = depth × 320`). The workspace re-lays
  nodes out vertically to fit its side panel.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `TRACEX_REPO` | (unset) | Index this repository at startup |
| `TRACEX_WORKSPACE_ROOT` | (unset) | Confine `POST /index` to paths inside this directory |
| `TRACEX_EMBED_MODEL` | `jinaai/jina-embeddings-v2-base-code` | Dense encoder (falls back to `BAAI/bge-m3`) |
| `TRACEX_RERANKER` | (unset) | `1` loads the cross-encoder and enables `rerank=true` |
| `TRACEX_RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder id |
| `TRACEX_DEVICE` | auto | Force `cuda` / `xpu` / `npu` / `mps` / `cpu` |
| `TRACEX_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |

> [!CAUTION]
> The API has no authentication, and `POST /index` reads arbitrary local directories.
> Bind it to localhost, or set `TRACEX_WORKSPACE_ROOT`, whenever anyone else can reach
> it. See [SECURITY.md](../SECURITY.md).
