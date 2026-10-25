import numpy as np
import pytest

from app.evaluation.stats import bootstrap_ci, holm_bonferroni, paired_randomization_test


def test_bootstrap_ci_contains_mean_and_is_seeded():
    values = np.linspace(0, 1, 40)
    low, high = bootstrap_ci(values, n_resamples=2000, seed=1)
    assert low < values.mean() < high
    assert (low, high) == bootstrap_ci(values, n_resamples=2000, seed=1)
    assert bootstrap_ci([0.5] * 10, n_resamples=100) == (0.5, 0.5)
    with pytest.raises(ValueError):
        bootstrap_ci([])


def test_randomization_test_identical_systems():
    a = np.array([0.1, 0.5, 0.9, 0.3])
    assert paired_randomization_test(a, a) == 1.0


def test_randomization_test_detects_consistent_improvement():
    rng = np.random.default_rng(0)
    base = rng.uniform(0, 0.5, size=30)
    better = base + 0.3
    p = paired_randomization_test(better, base, n_resamples=5000)
    assert p < 0.001
    # Symmetric: the test is two-sided.
    assert paired_randomization_test(base, better, n_resamples=5000) == p


def test_randomization_test_noise_is_not_significant():
    a = np.array([1.0, 0.0] * 10)
    b = np.array([0.0, 1.0] * 10)
    assert paired_randomization_test(a, b, n_resamples=2000) > 0.5


def test_holm_bonferroni():
    adjusted = holm_bonferroni({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})
    assert holm_bonferroni({"x": 0.6, "y": 0.9}) == {"x": 1.0, "y": 1.0}
