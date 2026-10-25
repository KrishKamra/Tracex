import math

import pytest

from app.parser import ASTEngine
from app.retrieval import CallGraph

P = "billing/payments.py::"
W = "billing/webhooks.py::"
S = "billing/storage.py::"
L = "billing/limits.py::"


@pytest.fixture(scope="module")
def graph(billing_symbols):
    return CallGraph(billing_symbols)


@pytest.mark.parametrize(
    ("caller", "callee", "mechanism"),
    [
        (P + "charge_customer", L + "check_limit", "relative from-import"),
        (P + "charge_customer", P + "PaymentGateway.create_charge", "parameter annotation"),
        (P + "charge_customer", S + "UsageStore.increment", "return annotation of UsageStore.default()"),
        (P + "charge_customer", S + "PaymentRepository.save", "Class().method chain"),
        (P + "refund_payment", S + "PaymentRepository.get", "local constructor assignment"),
        (L + "check_limit", L + "SpendingPolicy.is_exempt", "Optional[...] parameter annotation"),
        (W + "WebhookReceiver.handle", S + "AuditLog.record", "self attribute assigned in __init__"),
        (W + "WebhookReceiver.handle", W + "WebhookReceiver._on_dispute", "self method"),
        (P + "PaymentGateway.create_charge", P + "PaymentGateway._request", "self method"),
        ("billing/retry.py::retry.decorator.wrapper", "billing/retry.py::compute_backoff", "enclosing scope"),
        (
            "web/src/api/client.ts::ApiClient.request",
            "web/src/auth/session.ts::refreshAccessToken",
            "TS import",
        ),
        (
            "web/src/api/client.ts::ApiClient.getInvoices",
            "web/src/api/client.ts::ApiClient.request",
            "this method",
        ),
        (
            "web/src/components/InvoiceTable.tsx::InvoiceTable",
            "web/src/components/InvoiceTable.tsx::InvoiceTable.toggleSort",
            "nested arrow",
        ),
    ],
)
def test_call_resolution(graph, caller, callee, mechanism):
    assert callee in graph.callees(caller), mechanism


def test_callers_fan_in_fan_out(graph):
    assert graph.callers(L + "check_limit") == [P + "charge_customer"]
    assert graph.fan_in(S + "PaymentRepository.save") == 3
    assert graph.fan_out(W + "WebhookReceiver.handle") == 5


def test_external_calls_stay_unresolved(graph):
    callees = graph.callees("billing/notifications.py::notify_slack")
    assert callees == []  # requests.post is third-party
    assert any("requests.post" in u for u in graph.stats.unresolved_samples)
    assert 0 < graph.stats.resolution_rate < 1


def test_import_edges(graph):
    out = {v for _, v, k in graph.graph.out_edges("module::billing/payments.py", keys=True) if k == "IMPORTS"}
    assert L + "check_limit" in out
    assert "billing/retry.py::retry" in out


def _symbols(files):
    engine = ASTEngine()
    return [s for path, src in files.items() for s in engine.parse_source(src, "python", path).symbols]


def test_inheritance_super_and_inherited_methods():
    symbols = _symbols(
        {
            "base.py": (
                "class Base:\n    def save(self):\n        pass\n\n    def close(self):\n        pass\n"
            ),
            "child.py": (
                "from base import Base\n\n"
                "class Child(Base):\n"
                "    def save(self):\n"
                "        super().save()\n"
                "        self.close()\n"
            ),
        }
    )
    graph = CallGraph(symbols)
    assert graph.neighbors("child.py::Child") == ["base.py::Base"]
    assert graph.graph.has_edge("child.py::Child", "base.py::Base", key="INHERITS")
    assert graph.callees("child.py::Child.save") == ["base.py::Base.close", "base.py::Base.save"]


def test_untyped_local_shadows_global_and_unique_name_fallback():
    symbols = _symbols(
        {
            "a.py": "def helper():\n    pass\n\ndef run(items):\n    helper()\n    items.helper()\n",
            "b.py": "def other():\n    helper()\n",
        }
    )
    graph = CallGraph(symbols)
    assert graph.callees("a.py::run") == ["a.py::helper"]  # items.helper is untyped
    assert graph.callees("b.py::other") == ["a.py::helper"]  # repository-unique name


def test_graph_expansion_degree_damping():
    symbols = _symbols(
        {
            "m.py": (
                "def hub():\n    pass\n\n"
                "def a():\n    hub()\n    leaf()\n\n"
                "def b():\n    hub()\n\n"
                "def leaf():\n    pass\n"
            )
        }
    )
    graph = CallGraph(symbols)
    scores = graph.expand({"m.py::a": 1.0, "m.py::b": 0.5})
    # hub neighbours both seeds (deg 2); leaf only seed a (deg 1); b is a's 2-hop, not 1-hop.
    assert scores["m.py::hub"] == pytest.approx(1.5 / (1 + math.log(3)))
    assert scores["m.py::leaf"] == pytest.approx(1.0 / (1 + math.log(2)))
    assert "m.py::b" not in scores
