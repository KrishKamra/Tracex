"""Webhook billing service fixture for AST engine tests."""
import hashlib
from typing import Any
from .limits import check_limit as enforce_limit


class WebhookReceiver(BaseReceiver, metaclass=Registry):
    """Receives and validates incoming billing webhooks."""

    max_retries = 3

    def __init__(self, secret: str, timeout: float = 2.5) -> None:
        self.secret = secret
        self.timeout = timeout

    @staticmethod
    @retry(times=3)
    def validate_signature(payload: bytes, signature: str) -> bool:
        """Return True when the HMAC signature matches the payload."""
        digest = hashlib.sha256(payload).hexdigest()
        if digest != signature:
            raise SignatureError("bad signature")
        return True

    async def handle(self, event: dict[str, Any], *args, **kwargs):
        # Comment before body
        for item in event["items"]:
            enforce_limit(item)

        def _audit(entry):
            log_entry(entry)

        _audit(event)
        total = sum(x for x in args)
        return total


def check_limit(account_id: int, amount: float) -> bool:
    """Check whether the account is below its spending limit.

    Args:
        account_id: The billing account.
    """
    current, limit = fetch_usage(account_id), 100
    return current + amount <= limit
