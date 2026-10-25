"""Charging customers and issuing refunds through the payment provider."""

import requests

from .limits import check_limit
from .notifications import send_receipt_email
from .retry import retry
from .storage import AuditLog, PaymentRepository, UsageStore


class LimitExceededError(Exception):
    """Raised when a charge would push the account over its spending cap."""


class PaymentGateway:
    """Thin client for the external card processor's REST API."""

    def __init__(self, api_key: str, base_url: str = "https://api.processor.example/v1"):
        self.api_key = api_key
        self.base_url = base_url

    @retry(times=4)
    def _request(self, method: str, path: str, payload: dict) -> dict:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def create_charge(self, customer_id: str, amount: int, currency: str = "usd") -> dict:
        """Ask the processor to capture `amount` from the customer's default card."""
        return self._request(
            "POST", "/charges", {"customer": customer_id, "amount": amount, "currency": currency}
        )

    def create_refund(self, charge_id: str, amount: int | None = None) -> dict:
        return self._request("POST", "/refunds", {"charge": charge_id, "amount": amount})


def charge_customer(gateway: PaymentGateway, customer: dict, amount: int) -> dict:
    """Charge a customer after enforcing their spending limit, then persist and email a receipt."""
    if not check_limit(customer["account_id"], amount, tier=customer.get("tier", "standard")):
        raise LimitExceededError(customer["account_id"])
    charge = gateway.create_charge(customer["id"], amount)
    payment = {"id": charge["id"], "customer_id": customer["id"], "amount": amount, "status": "succeeded"}
    PaymentRepository().save(payment)
    UsageStore.default().increment(customer["account_id"], amount)
    send_receipt_email(customer, payment)
    return payment


def refund_payment(gateway: PaymentGateway, payment_id: str, reason: str = "requested_by_customer") -> dict:
    """Refund a previous payment in full and write the refund to the audit log."""
    repo = PaymentRepository()
    payment = repo.get(payment_id)
    if payment is None:
        raise KeyError(payment_id)
    gateway.create_refund(payment_id)
    payment["status"] = "refunded"
    repo.save(payment)
    AuditLog().record("refund", payment_id=payment_id, reason=reason)
    return payment
