# Tracex API (Phase 3)

A stateless FastAPI service over one immutable in-memory index. All contracts are
strict Pydantic v2 models (no coercion, unknown fields rejected). Interactive docs
are served at `/docs`.

```bash
TRACEX_REPO=eval/corpora/billing_service TRACEX_RERANKER=1 \
    uv run uvicorn app.api.main:app --port 8000
```

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/search?q=&dense=&bm25=&graph=&rerank=&top_k=` | Hybrid search with RRF breakdown and stage timings |
| `GET /api/v1/symbol/{symbol_id}` | File source, highlight span, scope table, imports, resolved call sites |
| `GET /api/v1/graph/{symbol_id}?depth=1..3` | Ego network shaped for `@xyflow/react`, with `+N` expanders |
| `POST /api/v1/index` `{"path": ...}` | (Re)index a repository; node/edge counts and parser versions |
| `GET /api/v1/index` · `GET /api/v1/health` | Index summary · liveness |

```mermaid
sequenceDiagram
    participant UI as Next.js workspace
    participant R as routes.py
    participant S as TracexService
    participant QP as query_parser
    participant E as HybridSearchEngine

    UI->>R: GET /search?q=@handle verify signature
    R->>S: search(q, pillars, top_k)
    S->>QP: parse_query → {symbol: handle, text: verify signature}
    QP-->>S: allowed = apply_filters(symbols)
    S->>E: retrieve(text, allowed) → fuse(config, allowed)
    E-->>S: hits + ranks + contributions + timings
    S-->>R: SearchResponse (strict schema)
    R-->>UI: JSON + Server-Timing: embedding;dur=… bm25;dur=… app;dur=…
```

## Query prefixes

| Prefix | Filter | Example |
| --- | --- | --- |
| `@name` | symbol name / qualified name (exact > prefix > suffix > substring) | `@save` |
| `#route` | effective route: class decorator prefix joined with the method route | `#/webhooks/stripe` |
| `/path` | file path, anchored at a segment boundary | `/web/` matches `web/…`, not `billing/webhooks.py` |

Filters are ANDed. The remaining words are ranked by the hybrid engine **within**
the filtered set. A filter-only query returns matches ordered by filter quality,
with `match_origin = ["filter"]`.

## Contracts the frontend relies on

- **Search hits** carry `dense_rank`, `bm25_rank`, `graph_rank`, `rrf_score`,
  per-pillar `contributions` (summing to `rrf_score`), `match_origin`,
  `matched_terms`, a `snippet` and a `summary`. They feed the RRF explainability popover.
- **Symbol detail** gives `highlight` (lines + bytes) and `call_sites[]` (`callee`,
  `line`, resolved `target_id`). Two calls on the same line resolve independently.
  These drive the cyan trace highlights and `g d` go-to-definition.
- **Graph** nodes have `position` (layered: x = depth × 320, callers left, callees
  right), `data.role`, and `hidden_callers` / `hidden_callees` for `+N` expanders.
  Edges carry `call_lines`.

> [!NOTE]
> **Telemetry.** Every response has `X-Response-Time-Ms` and a `Server-Timing`
> header. Search adds one entry per pipeline stage, so browser devtools show the
> breakdown natively. Measured on CPU with jina-embeddings-v2: ~86 ms per search,
> almost all of it query embedding; BM25, graph and RRF together take < 3 ms.
> Reranking adds ~0.6 s.

> [!WARNING]
> `POST /index` reads arbitrary local directories. Set `TRACEX_WORKSPACE_ROOT` to
> confine it whenever the server is reachable by anyone but you. Indexing runs
> synchronously. Embedding dominates (~0.5 s per chunk on CPU), so index large
> repositories on a GPU, or before starting the server via `TRACEX_REPO`.

| Status | Meaning |
| --- | --- |
| 400 | bad index path, or `rerank=true` without a loaded reranker |
| 404 | unknown `symbol_id` |
| 409 | nothing indexed yet |
| 422 | schema violation (e.g. `top_k=0`, `depth=4`, both `dense` and `bm25` off) |
