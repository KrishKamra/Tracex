"""FastAPI application factory.

Run locally::

    TRACEX_REPO=../some/repo uv run uvicorn app.api.main:app --reload

Environment:

=======================  =====================================================
``TRACEX_REPO``          repository to index at startup (optional)
``TRACEX_WORKSPACE_ROOT`` if set, ``POST /index`` only accepts paths inside it
``TRACEX_EMBED_MODEL``   dense model (default jina-embeddings-v2-base-code)
``TRACEX_RERANKER``      ``1`` to load the cross-encoder (enables ``rerank=true``)
``TRACEX_RERANK_MODEL``  cross-encoder model id
``TRACEX_DEVICE``        force cuda / xpu / npu / mps / cpu
``TRACEX_CORS_ORIGINS``  comma-separated origins (default http://localhost:3000)
=======================  =====================================================
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import API_VERSION, router
from app.api.service import TracexService

logger = logging.getLogger(__name__)


def default_service() -> TracexService:
    from app.nlp.embeddings import DEFAULT_MODEL, FALLBACK_MODELS, CodeEmbedder
    from app.retrieval.reranker import DEFAULT_RERANKER, CrossEncoderReranker

    model = os.environ.get("TRACEX_EMBED_MODEL", DEFAULT_MODEL)
    fallbacks = FALLBACK_MODELS if model == DEFAULT_MODEL else ()

    def reranker() -> CrossEncoderReranker | None:
        if os.environ.get("TRACEX_RERANKER") != "1":
            return None
        return CrossEncoderReranker(os.environ.get("TRACEX_RERANK_MODEL", DEFAULT_RERANKER))

    return TracexService(
        lambda: CodeEmbedder(model, fallback_models=fallbacks),
        reranker,
        workspace_root=os.environ.get("TRACEX_WORKSPACE_ROOT"),
    )


def create_app(service: TracexService | None = None, *, index_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo = index_path or os.environ.get("TRACEX_REPO")
        if repo:
            summary = app.state.service.index_repository(repo)
            logger.info("Indexed %s: %d symbols in %.0f ms", repo, summary.symbols, summary.duration_ms)
        yield

    app = FastAPI(
        title="Tracex API",
        version=API_VERSION,
        description="AST-aware hybrid code search: BM25 + dense + call graph, fused by weighted RRF.",
        lifespan=lifespan,
    )
    app.state.service = service or default_service()
    origins = os.environ.get("TRACEX_CORS_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["Server-Timing", "X-Response-Time-Ms"],
    )

    @app.middleware("http")
    async def telemetry(request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        stages = getattr(request.state, "server_timing", {})
        entries = [f"{name};dur={value:.3f}" for name, value in stages.items()] + [f"app;dur={elapsed:.3f}"]
        response.headers["Server-Timing"] = ", ".join(entries)
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.3f}"
        return response

    app.include_router(router)
    return app


app = create_app()
