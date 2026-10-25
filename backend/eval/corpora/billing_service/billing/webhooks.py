"""Inbound webhooks from the payment processor."""

import hashlib
import hmac
import json

from .notifications import notify_slack
from .storage import AuditLog, PaymentRepository


class SignatureError(Exception):
    """The webhook payload was not signed with our shared secret."""


def parse_event(raw_body: bytes) -> dict:
    """Decode the JSON webhook body into an event dict with `type` and `data`."""
    event = json.loads(raw_body)
    if "type" not in event:
        raise ValueError("malformed event")
    return event


class WebhookReceiver:
    """Verifies and dispatches processor webhook events."""

    def __init__(self, secret: str):
        self.secret = secret.encode()
        self.audit = AuditLog()

    def validate_signature(self, payload: bytes, signature: str) -> None:
        """Reject payloads whose HMAC-SHA256 digest does not match the signature header."""
        expected = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise SignatureError("invalid webhook signature")

    def handle(self, payload: bytes, signature: str) -> None:
        """Entry point: verify the request, then route it by event type."""
        self.validate_signature(payload, signature)
        event = parse_event(payload)
        if event["type"] == "payment.failed":
            self._on_payment_failed(event["data"])
        elif event["type"] == "charge.disputed":
            self._on_dispute(event["data"])
        self.audit.record("webhook", event_type=event["type"])

    def _on_payment_failed(self, data: dict) -> None:
        repo = PaymentRepository()
        payment = repo.get(data["payment_id"])
        if payment:
            payment["status"] = "failed"
            repo.save(payment)

    def _on_dispute(self, data: dict) -> None:
        """A cardholder disputed a charge (chargeback): alert the finance channel."""
        notify_slack("#finance-alerts", f"Chargeback opened for payment {data['payment_id']}")
