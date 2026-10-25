# Tracex Backend

AST-aware hybrid NLP engine for codebase semantic search and dependency intelligence.

```bash
uv sync          # Python 3.12, installs tree-sitter + sentence-transformers
uv run pytest    # test suite (no model downloads)
uv run python -m app.evaluation.benchmark --output eval/reports/billing_service.md   # ablation benchmark
TRACEX_REPO=eval/corpora/billing_service uv run uvicorn app.api.main:app   # API on :8000, docs at /docs
```

| Phase | Package | Status |
| --- | --- | --- |
| 1. Inference layer | [`app/parser`](app/parser), [`app/nlp`](app/nlp) | ✅ see [`app/README.md`](app/README.md) |
| 2. Hybrid retrieval & RRF | [`app/retrieval`](app/retrieval), [`app/evaluation`](app/evaluation) | ✅ see [`app/retrieval/README.md`](app/retrieval/README.md), [`app/evaluation/README.md`](app/evaluation/README.md) |
| 3. FastAPI service | [`app/api`](app/api) | ✅ see [`app/api/README.md`](app/api/README.md) |
