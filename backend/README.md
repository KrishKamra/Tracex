# Tracex Backend

AST-aware hybrid NLP engine for codebase semantic search and dependency intelligence.

```bash
uv sync          # Python 3.12, installs tree-sitter + sentence-transformers
uv run pytest    # Phase 1 test suite
```

| Phase | Package | Status |
| --- | --- | --- |
| 1. Inference layer | [`app/parser`](app/parser), [`app/nlp`](app/nlp) | ✅ see [`app/README.md`](app/README.md) |
| 2. Hybrid retrieval & RRF | `app/retrieval`, `app/evaluation` | planned |
| 3. FastAPI service | `app/api` | planned |
