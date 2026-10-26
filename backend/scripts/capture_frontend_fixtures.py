"""Capture real API payloads as frontend test fixtures.

    cd backend
    uv run python scripts/capture_frontend_fixtures.py

Runs the FastAPI app in-process over the benchmark corpus with the test suite's
deterministic hashing embedder (no model download), then writes the responses
to frontend/tests/fixtures/*.json. Run it whenever the API contract changes, so
the frontend's types and tests are checked against what the server returns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.api.service import TracexService  # noqa: E402
from tests.conftest import make_hashing_embedder  # noqa: E402

OUT = BACKEND.parent / "frontend" / "tests" / "fixtures"
CORPUS = BACKEND / "eval" / "corpora" / "billing_service"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(TracexService(make_hashing_embedder), index_path=str(CORPUS))) as client:
        index = client.get("/api/v1/index").json()
        # Machine-independent values, so fixtures do not churn between runs.
        index["repository"] = "/repos/billing_service"
        index["build_ms"] = {k: 1.0 for k in index["build_ms"]}
        index["duration_ms"] = 10.0
        search = client.get("/api/v1/search", params={"q": "check spending limit", "top_k": 5}).json()
        search["timings"] = {k: 1.0 for k in search["timings"]}
        payloads = {
            "index": index,
            "search": search,
            "symbol": client.get("/api/v1/symbol/billing/payments.py::charge_customer").json(),
            "graph": client.get("/api/v1/graph/billing/payments.py::charge_customer").json(),
            "graph_check_limit": client.get("/api/v1/graph/billing/limits.py::check_limit").json(),
        }
    for name, payload in payloads.items():
        (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
