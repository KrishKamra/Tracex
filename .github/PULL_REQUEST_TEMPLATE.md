## What and why

<!-- What does this change, and why is it needed? Link issues with "Closes #123". -->

## Type

- [ ] `feat`: new capability
- [ ] `fix`: bug fix
- [ ] `perf` / `refactor`: no behaviour change intended
- [ ] `docs` / `test` / `chore`

## Retrieval impact

<!-- Required if this can change rankings (parser, tokenizer, serializer, embedder, BM25, graph, RRF, reranker). -->

- [ ] Not applicable: rankings cannot change
- [ ] Benchmark re-run and report + figures committed (`app.evaluation.benchmark`, `docs/scripts/make_figures.py`)

| Configuration | NDCG@5 before | NDCG@5 after | Δ | p_adj vs before |
|---|---:|---:|---:|---:|
| Full Tracex (CV-tuned) | | | | |

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest` (backend)
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` (frontend)
- [ ] API contract changed → `schemas.py`, `types.ts`, fixtures (`backend/scripts/capture_frontend_fixtures.py`) and `docs/api-spec.md` updated
- [ ] UI changed → light and dark screenshots attached
- [ ] `CHANGELOG.md` updated under **Unreleased**
