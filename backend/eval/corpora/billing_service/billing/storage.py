"""Persistence for payments, usage counters and the audit trail."""

import json
import sqlite3
from datetime import UTC, datetime


class PaymentRepository:
    """SQLite-backed store of payment records."""

    def __init__(self, path: str = "billing.db"):
        self.conn = sqlite3.connect(path)

    def save(self, payment: dict) -> None:
        """Insert or update a payment row keyed by its id."""
        self.conn.execute(
            "INSERT OR REPLACE INTO payments (id, customer_id, amount, status) VALUES (?, ?, ?, ?)",
            (payment["id"], payment["customer_id"], payment["amount"], payment["status"]),
        )
        self.conn.commit()

    def get(self, payment_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, customer_id, amount, status FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()
        return dict(zip(("id", "customer_id", "amount", "status"), row)) if row else None

    def list_by_customer(self, customer_id: str) -> list[dict]:
        """All payments for a customer, newest first."""
        rows = self.conn.execute(
            "SELECT id FROM payments WHERE customer_id = ? ORDER BY rowid DESC", (customer_id,)
        )
        return [self.get(r[0]) for r in rows]


class UsageStore:
    """Month-to-date spend counters."""

    _instance = None

    @classmethod
    def default(cls) -> "UsageStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.totals: dict[str, int] = {}

    def month_to_date(self, account_id: str) -> int:
        return self.totals.get(account_id, 0)

    def increment(self, account_id: str, amount: int) -> None:
        self.totals[account_id] = self.totals.get(account_id, 0) + amount


class AuditLog:
    """Append-only JSON-lines audit trail for compliance."""

    def __init__(self, path: str = "audit.log"):
        self.path = path

    def record(self, action: str, **details) -> None:
        """Append a timestamped entry describing a billing action."""
        entry = {"ts": datetime.now(UTC).isoformat(), "action": action, **details}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
