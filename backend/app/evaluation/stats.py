"""Statistical significance for IR comparisons over a shared query set.

* Percentile bootstrap CI: resample queries with replacement and take the
  (alpha/2, 1 - alpha/2) percentiles of the resampled means.
* Paired approximate randomization (sign-flip permutation) test: under H0
  the two systems are exchangeable per query, so each per-query difference
  d_i = a_i - b_i keeps its magnitude and gets a random sign:

      p = (1 + #{ |mean(s * d)| >= |mean(d)| }) / (1 + R)

  This is the test recommended for IR by Smucker et al. (CIKM 2007).
* Holm-Bonferroni step-down correction controls the family-wise error rate
  when one baseline is compared against several systems and metrics.

All procedures are seeded, so reports are reproducible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


def bootstrap_ci(
    values: Sequence[float], *, n_resamples: int = 10_000, confidence: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    data = np.asarray(values, dtype=np.float64)
    if data.size == 0:
        raise ValueError("cannot bootstrap an empty sample")
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, data.size, size=(n_resamples, data.size))].mean(axis=1)
    alpha = (1 - confidence) / 2
    low, high = np.quantile(means, [alpha, 1 - alpha])
    return float(low), float(high)


def paired_randomization_test(
    a: Sequence[float], b: Sequence[float], *, n_resamples: int = 10_000, seed: int = 0
) -> float:
    """Two-sided p-value for H0: mean(a) == mean(b) on paired per-query scores."""
    diff = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    if diff.ndim != 1 or diff.size == 0:
        raise ValueError("a and b must be equal-length non-empty 1-D samples")
    observed = abs(diff.mean())
    if np.allclose(diff, 0):
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice((-1.0, 1.0), size=(n_resamples, diff.size))
    null = np.abs((signs * diff).mean(axis=1))
    return float((1 + np.count_nonzero(null >= observed - 1e-12)) / (1 + n_resamples))


def holm_bonferroni(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values (monotone, capped at 1)."""
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[key] = running
    return {key: adjusted[key] for key in p_values}
