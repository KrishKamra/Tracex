"""Spending limits and usage accounting for customer accounts."""

from .storage import UsageStore

DEFAULT_MONTHLY_CAP = 10_000


class SpendingPolicy:
    """Per-account policy describing caps and exemptions."""

    def __init__(
        self, monthly_cap: int = DEFAULT_MONTHLY_CAP, exempt_tiers: tuple[str, ...] = ("enterprise",)
    ):
        self.monthly_cap = monthly_cap
        self.exempt_tiers = exempt_tiers

    def is_exempt(self, tier: str) -> bool:
        """Enterprise tiers bypass the monthly cap entirely."""
        return tier in self.exempt_tiers


def fetch_usage(account_id: str) -> int:
    """Return the amount the account has spent so far this month, in cents."""
    return UsageStore.default().month_to_date(account_id)


def check_limit(
    account_id: str, amount: int, tier: str = "standard", policy: SpendingPolicy | None = None
) -> bool:
    """Return True if charging `amount` keeps the account within its monthly budget."""
    policy = policy or SpendingPolicy()
    if policy.is_exempt(tier):
        return True
    return fetch_usage(account_id) + amount <= policy.monthly_cap
