"""Retry helpers for flaky network calls."""

import functools
import random
import time


def compute_backoff(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter: sleep a random time in [0, min(cap, base * 2**attempt)]."""
    return random.uniform(0, min(cap, base * 2**attempt))


def retry(times: int = 3, exceptions: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)):
    """Decorator that re-invokes the wrapped function when it raises a transient error."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    if attempt == times - 1:
                        raise
                    time.sleep(compute_backoff(attempt))

        return wrapper

    return decorator
