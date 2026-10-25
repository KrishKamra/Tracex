"""REST routes: /api/v1/{search, symbol, graph, index, health}."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.api import schemas
from app.api.service import IndexPathError, NotIndexedError, SymbolNotFoundError, TracexService

router = APIRouter(prefix="/api/v1")
API_VERSION = "0.3.0"


def get_service(request: Request) -> TracexService:
    return request.app.state.service


Service = Annotated[TracexService, Depends(get_service)]
SymbolId = Annotated[str, Path(description="Symbol id, e.g. `billing/payments.py::charge_customer`")]


def _not_indexed(exc: NotIndexedError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/health", response_model=schemas.HealthResponse)
def health(service: Service) -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", indexed=service.indexed, version=API_VERSION)


@router.get("/search", response_model=schemas.SearchResponse)
def search(
    request: Request,
    service: Service,
    q: Annotated[
        str, Query(min_length=1, max_length=500, description="Query; supports @symbol #route /path")
    ],
    dense: bool = True,
    bm25: bool = True,
    graph: bool = True,
    rerank: bool = False,
    top_k: Annotated[int, Query(ge=1, le=100)] = 10,
) -> schemas.SearchResponse:
    if not (dense or bm25):
        raise HTTPException(422, detail="enable at least one of dense or bm25")
    try:
        response = service.search(q, dense=dense, bm25=bm25, graph=graph, rerank=rerank, top_k=top_k)
    except NotIndexedError as exc:
        raise _not_indexed(exc) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    request.state.server_timing = {
        name.removesuffix("_ms"): value for name, value in response.timings.model_dump().items() if value
    }
    return response


@router.get("/symbol/{symbol_id:path}", response_model=schemas.SymbolDetail)
def symbol(service: Service, symbol_id: SymbolId) -> schemas.SymbolDetail:
    try:
        return service.symbol_detail(symbol_id)
    except NotIndexedError as exc:
        raise _not_indexed(exc) from exc
    except SymbolNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown symbol: {symbol_id}") from exc


@router.get("/graph/{symbol_id:path}", response_model=schemas.GraphResponse)
def graph(
    service: Service,
    symbol_id: SymbolId,
    depth: Annotated[int, Query(ge=1, le=3, description="Hops upstream and downstream")] = 1,
) -> schemas.GraphResponse:
    try:
        return service.call_graph(symbol_id, depth)
    except NotIndexedError as exc:
        raise _not_indexed(exc) from exc
    except SymbolNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown symbol: {symbol_id}") from exc


@router.post("/index", response_model=schemas.IndexResponse)
def index(service: Service, body: schemas.IndexRequest) -> schemas.IndexResponse:
    try:
        return service.index_repository(body.path)
    except IndexPathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/index", response_model=schemas.IndexResponse)
def index_status(service: Service) -> schemas.IndexResponse:
    try:
        return service.index_status()
    except NotIndexedError as exc:
        raise _not_indexed(exc) from exc
