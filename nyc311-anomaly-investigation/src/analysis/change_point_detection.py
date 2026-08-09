"""Formal change-point detection — never eyeball a chart."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ChangePoint:
    index: pd.Timestamp
    mean_before: float
    mean_after: float
    pct_change: float


def detect_change_points(series: pd.Series, model: str = "rbf",
                         penalty: float = 10.0, min_size: int = 14) -> list[pd.Timestamp]:
    """Return breakpoint timestamps using PELT (ruptures)."""
    import ruptures as rpt

    values = series.to_numpy(dtype=float).reshape(-1, 1)
    algo = rpt.Pelt(model=model, min_size=min_size).fit(values)
    breaks = algo.predict(pen=penalty)
    return [series.index[i] for i in breaks if i < len(series)]


def cusum(series: pd.Series, threshold: float = 5.0, drift: float = 0.5,
          baseline_periods: int | None = None) -> pd.DataFrame:
    """Two-sided standardized CUSUM; flags sustained level shifts.

    Standardization uses a baseline (in-control) window — the first
    `baseline_periods` points, or the whole series when not supplied — so a shift
    later in the series does not contaminate the reference mean.
    """
    x = series.to_numpy(dtype=float)
    ref = x[:baseline_periods] if baseline_periods else x
    mu = ref.mean()
    sigma = ref.std(ddof=1) or 1.0
    z = (x - mu) / sigma
    pos = np.zeros_like(z)
    neg = np.zeros_like(z)
    for i in range(1, len(z)):
        pos[i] = max(0.0, pos[i - 1] + z[i] - drift)
        neg[i] = min(0.0, neg[i - 1] + z[i] + drift)
    return pd.DataFrame(
        {"cusum_pos": pos, "cusum_neg": neg,
         "alarm": (pos > threshold) | (neg < -threshold)},
        index=series.index,
    )


def summarize_shift(series: pd.Series, breakpoint: pd.Timestamp) -> ChangePoint:
    before = series.loc[series.index < breakpoint]
    after = series.loc[series.index >= breakpoint]
    mb, ma = float(before.mean()), float(after.mean())
    return ChangePoint(breakpoint, mb, ma, (ma - mb) / mb * 100 if mb else float("nan"))


def rolling_bands(series: pd.Series, window: int = 28, sigma: float = 2.0) -> pd.DataFrame:
    mean = series.rolling(window, min_periods=window // 2).mean()
    std = series.rolling(window, min_periods=window // 2).std(ddof=1)
    return pd.DataFrame({"value": series, "mean": mean,
                         "upper": mean + sigma * std, "lower": mean - sigma * std})
