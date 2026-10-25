from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.query_parser import apply_filters, effective_routes, parse_query
from app.api.service import TracexService
from app.parser import ASTEngine
from app.retrieval import CrossEncoderReranker
from tests.conftest import make_hashing_embedder

FIXTURES = Path(__file__).parent / "fixtures"
P = "billing/payments.py::"


class OverlapCrossEncoder:
    def predict(self, pairs, **kwargs):
        return np.array([len(set(q.lower().split()) & set(t.lower().split())) for q, t in pairs], dtype=float)


def make_service(**kwargs) -> TracexService:
    return TracexService(
        make_hashing_embedder,
        lambda: CrossEncoderReranker("overlap", device="cpu", loader=lambda *a: OverlapCrossEncoder()),
        **kwargs,
    )


@pytest.fixture(scope="module")
def client(billing_dataset):
    app = create_app(make_service(), index_path=str(billing_dataset.corpus_root))
    with TestClient(app) as test_client:  # runs the lifespan, which indexes the corpus
        yield test_client


# --------------------------------------------------------------------------- #
# Query parser
# --------------------------------------------------------------------------- #


def test_parse_query_prefixes():
    parsed = parse_query("@handle #webhooks /api verify signature")
    assert (parsed.symbol, parsed.route, parsed.path, parsed.text) == (
        "handle",
        "/webhooks",
        "api",
        "verify signature",
    )
    assert parse_query("#/a/b").route == "/a/b"
    plain = parse_query("refund money")
    assert not plain.has_filters and plain.text == "refund money"
    assert parse_query("@ / #").text == "@ / #"  # bare sigils are plain text


def test_effective_routes_join_class_prefix():
    symbols = ASTEngine().parse_file(FIXTURES / "sample_router.ts", FIXTURES).symbols
    by_qualified = {(s.file_path, s.qualified_name): s for s in symbols}
    handler = next(s for s in symbols if s.name == "handleStripe")
    assert "/webhooks/stripe" in effective_routes(handler, by_qualified)
    assert effective_routes(next(s for s in symbols if s.name == "parseEvent"), by_qualified) == []
    assert [s.name for s in apply_filters(parse_query("#/webhooks/stripe"), symbols)] == ["handleStripe"]


def test_symbol_filter_ranks_exact_matches_first(billing_symbols):
    names = [s.qualified_name for s in apply_filters(parse_query("@save"), billing_symbols)]
    assert names[0] == "PaymentRepository.save"
    assert all("save" in n.lower() for n in names)


# --------------------------------------------------------------------------- #
# Lifecycle and indexing
# --------------------------------------------------------------------------- #


def test_requests_before_indexing_return_409():
    with TestClient(create_app(make_service())) as fresh:
        assert fresh.get("/api/v1/health").json() == {"status": "ok", "indexed": False, "version": "0.3.0"}
        assert fresh.get("/api/v1/search", params={"q": "x"}).status_code == 409
        assert fresh.get("/api/v1/index").status_code == 409


def test_index_endpoint(tmp_path):
    with TestClient(create_app(make_service(workspace_root=FIXTURES))) as fresh:
        response = fresh.post("/api/v1/index", json={"path": str(FIXTURES)})
        assert response.status_code == 200
        body = response.json()
        assert body["symbols"] == 13 and body["files"] == 2
        assert body["languages"] == {"python": 1, "typescript": 1}
        assert set(body["parser_versions"]) == {"tree-sitter", "tree-sitter-python", "tree-sitter-typescript"}
        assert body["edges"]["CALLS"] > 0
        assert fresh.get("/api/v1/index").json()["symbols"] == 13

        assert (
            fresh.post("/api/v1/index", json={"path": str(tmp_path)}).status_code == 400
        )  # outside workspace
        assert fresh.post("/api/v1/index", json={"path": str(FIXTURES / "nope")}).status_code == 400
        assert fresh.post("/api/v1/index", json={"path": 42}).status_code == 422  # strict schema
        assert fresh.post("/api/v1/index", json={"path": "x", "extra": 1}).status_code == 422


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


def test_search_returns_rrf_breakdown_and_telemetry(client):
    response = client.get("/api/v1/search", params={"q": "check_limit", "top_k": 5})
    assert response.status_code == 200
    body = response.json()
    top = body["hits"][0]
    assert top["symbol_id"] == "billing/limits.py::check_limit"
    assert top["bm25_rank"] == 1 and top["dense_rank"] is not None
    assert top["rrf_score"] == pytest.approx(sum(top["contributions"].values()))
    assert "check_limit" in top["matched_terms"]
    assert top["snippet"].startswith("def check_limit(")
    assert top["summary"].startswith("Return True if charging")
    assert body["pillars"] == ["dense", "bm25", "graph"]
    timings = body["timings"]
    assert timings["total_ms"] >= timings["bm25_ms"] > 0
    assert "app;dur=" in response.headers["server-timing"]
    assert "bm25;dur=" in response.headers["server-timing"]
    assert float(response.headers["x-response-time-ms"]) > 0


def test_search_pillar_toggles_and_rerank(client):
    body = client.get("/api/v1/search", params={"q": "refund payment", "dense": False, "graph": False}).json()
    assert body["pillars"] == ["bm25"]
    assert all(h["dense_rank"] is None and h["graph_rank"] is None for h in body["hits"])

    reranked = client.get("/api/v1/search", params={"q": "refund payment", "rerank": True}).json()
    assert reranked["reranked"] is True
    scores = [h["rerank_score"] for h in reranked["hits"]]
    assert scores == sorted(scores, reverse=True)

    assert client.get("/api/v1/search", params={"q": "x", "dense": False, "bm25": False}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "x", "top_k": 0}).status_code == 422
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422


def test_search_with_prefix_filters(client):
    body = client.get("/api/v1/search", params={"q": "/web/ invoices"}).json()
    assert body["query"]["path"] == "web/" and body["query"]["text"] == "invoices"
    assert body["hits"] and all(h["file_path"].startswith("web/") for h in body["hits"])
    assert body["candidates"] < 65
    # Segment-anchored: /hooks matches web/src/hooks/ but not billing/webhooks.py.
    hooks = client.get("/api/v1/search", params={"q": "/hooks invoices"}).json()
    assert {h["file_path"] for h in hooks["hits"]} == {"web/src/hooks/useInvoices.ts"}

    only_filter = client.get("/api/v1/search", params={"q": "@check_limit"}).json()
    assert only_filter["hits"][0]["symbol_id"] == "billing/limits.py::check_limit"
    assert only_filter["hits"][0]["match_origin"] == ["filter"]
    assert only_filter["pillars"] == []

    assert client.get("/api/v1/search", params={"q": "@does_not_exist refund"}).json()["hits"] == []


def test_rerank_without_model_is_rejected():
    service = TracexService(make_hashing_embedder)
    with TestClient(create_app(service, index_path=str(FIXTURES))) as fresh:
        response = fresh.get("/api/v1/search", params={"q": "x", "rerank": True})
        assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Symbol inspector
# --------------------------------------------------------------------------- #


def test_symbol_detail(client):
    response = client.get(f"/api/v1/symbol/{P}refund_payment")
    assert response.status_code == 200
    body = response.json()
    lines = body["file"]["source"].split("\n")
    assert lines[body["highlight"]["start_line"] - 1].startswith("def refund_payment(")
    assert lines[body["highlight"]["end_line"] - 1].strip() == "return payment"
    assert [p["name"] for p in body["scope"]["params"]] == ["gateway", "payment_id", "reason"]
    assert body["scope"]["raises"] == ["KeyError"]
    assert {"module": ".limits", "name": "check_limit", "alias": None, "line": 5} in body["imports"]
    sites = {s["callee"]: s for s in body["call_sites"]}
    save = sites["repo.save"]
    assert save["target_id"] == "billing/storage.py::PaymentRepository.save"
    assert "repo.save(payment)" in lines[save["line"] - 1]
    assert sites["KeyError"]["target_id"] is None
    assert body["fan_out"] == 6


def test_call_sites_on_the_same_line_resolve_independently(client):
    body = client.get(f"/api/v1/symbol/{P}charge_customer").json()
    targets = {s["callee"]: s["target_id"] for s in body["call_sites"]}
    lines = {s["callee"]: s["line"] for s in body["call_sites"]}
    assert lines["check_limit"] == lines["customer.get"]  # `if not check_limit(..., tier=customer.get(...))`
    assert targets["check_limit"] == "billing/limits.py::check_limit"
    assert targets["customer.get"] is None


def test_symbol_detail_routes_and_404(client):
    assert client.get("/api/v1/symbol/nope.py::missing").status_code == 404
    with TestClient(create_app(make_service(), index_path=str(FIXTURES))) as fresh:
        body = fresh.get("/api/v1/symbol/sample_router.ts::PaymentRouter.handleStripe").json()
        assert "/webhooks/stripe" in body["routes"]


# --------------------------------------------------------------------------- #
# Call graph
# --------------------------------------------------------------------------- #


def test_graph_ego_network(client):
    body = client.get("/api/v1/graph/billing/limits.py::check_limit").json()
    nodes = {n["id"]: n for n in body["nodes"]}
    focus = nodes["billing/limits.py::check_limit"]
    caller = nodes[P + "charge_customer"]
    callee = nodes["billing/limits.py::fetch_usage"]
    assert focus["data"]["role"] == "focus" and focus["position"] == {"x": 0.0, "y": 0.0}
    assert (
        caller["data"]["role"] == "caller" and caller["data"]["depth"] == -1 and caller["position"]["x"] < 0
    )
    assert callee["data"]["role"] == "callee" and callee["position"]["x"] > 0
    assert focus["type"] == "symbol"
    # fetch_usage has its own callees beyond depth 1: shown as a "+N" expander.
    assert callee["data"]["hidden_callees"] == 2
    edge = next(e for e in body["edges"] if e["source"] == P + "charge_customer")
    assert edge["target"] == focus["id"] and edge["data"]["kind"] == "CALLS" and edge["data"]["call_lines"]
    assert body["fan_in"] == 1 and body["fan_out"] == 3


def test_graph_depth(client):
    deep = client.get("/api/v1/graph/billing/limits.py::check_limit", params={"depth": 2}).json()
    nodes = {n["id"]: n for n in deep["nodes"]}
    assert nodes["billing/storage.py::UsageStore.month_to_date"]["data"]["depth"] == 2
    assert nodes["billing/limits.py::fetch_usage"]["data"]["hidden_callees"] == 0
    assert client.get("/api/v1/graph/billing/limits.py::check_limit", params={"depth": 4}).status_code == 422
    assert client.get("/api/v1/graph/nope.py::x").status_code == 404


def test_openapi_schema_lists_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/search",
        "/api/v1/index",
        "/api/v1/symbol/{symbol_id}",
        "/api/v1/graph/{symbol_id}",
    } <= set(paths)
