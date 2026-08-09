"""Thin, tested wrappers around scipy so notebooks report p-values, not vibes."""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class TestResult:
    name: str
    statistic: float
    p_value: float
    significant: bool
    detail: dict

    def as_dict(self) -> dict:
        return asdict(self)


def two_proportion_ztest(success_a: int, n_a: int, success_b: int, n_b: int,
                         alpha: float = 0.01) -> TestResult:
    if n_a <= 0 or n_b <= 0:
        raise ValueError("sample sizes must be positive")
    p_a, p_b = success_a / n_a, success_b / n_b
    pooled = (success_a + success_b) / (n_a + n_b)
    se = np.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z = 0.0 if se == 0 else (p_a - p_b) / se
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return TestResult("two_proportion_ztest", float(z), float(p), p < alpha,
                      {"p_a": p_a, "p_b": p_b, "diff": p_a - p_b})


def chi_square_independence(table, alpha: float = 0.01) -> TestResult:
    chi2, p, dof, expected = stats.chi2_contingency(np.asarray(table, dtype=float))
    n = np.asarray(table, dtype=float).sum()
    min_dim = min(np.asarray(table).shape) - 1
    cramers_v = float(np.sqrt(chi2 / (n * min_dim))) if n and min_dim else float("nan")
    return TestResult("chi_square_independence", float(chi2), float(p), p < alpha,
                      {"dof": int(dof), "cramers_v": cramers_v,
                       "expected": expected.tolist()})


def welch_ttest(a, b, alpha: float = 0.01) -> TestResult:
    t, p = stats.ttest_ind(np.asarray(a, dtype=float), np.asarray(b, dtype=float),
                           equal_var=False)
    return TestResult("welch_ttest", float(t), float(p), p < alpha,
                      {"mean_a": float(np.mean(a)), "mean_b": float(np.mean(b))})


def mann_whitney(a, b, alpha: float = 0.01) -> TestResult:
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    return TestResult("mann_whitney_u", float(u), float(p), p < alpha, {})


def benjamini_hochberg(p_values, alpha: float = 0.01) -> list[bool]:
    """FDR control — you will run many tests; correct for it."""
    p = np.asarray(p_values, dtype=float)
    order = np.argsort(p)
    m = len(p)
    thresholds = alpha * (np.arange(1, m + 1) / m)
    passed = p[order] <= thresholds
    cutoff = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    keep = np.zeros(m, dtype=bool)
    keep[order[:cutoff]] = True
    return keep.tolist()
