"""Seasonality controls: STL decomposition and seasonal-baseline deviation."""
from __future__ import annotations

import pandas as pd
from statsmodels.tsa.seasonal import STL


def stl_decompose(series: pd.Series, period: int = 7, robust: bool = True) -> pd.DataFrame:
    result = STL(series.astype(float), period=period, robust=robust).fit()
    return pd.DataFrame({"observed": series, "trend": result.trend,
                         "seasonal": result.seasonal, "resid": result.resid})


def seasonal_baseline_sigma(series: pd.Series, window_start: str, window_end: str,
                            baseline_years: int = 3) -> dict[str, float]:
    """Compare a window against the same calendar window in prior years."""
    idx = pd.to_datetime(series.index)
    series = pd.Series(series.values, index=idx)
    start, end = pd.Timestamp(window_start), pd.Timestamp(window_end)
    current = float(series.loc[start:end].sum())

    priors = []
    for k in range(1, baseline_years + 1):
        s, e = start - pd.DateOffset(years=k), end - pd.DateOffset(years=k)
        chunk = series.loc[s:e]
        if len(chunk):
            priors.append(float(chunk.sum()))

    baseline = pd.Series(priors, dtype=float)
    std = float(baseline.std(ddof=1)) if len(baseline) > 1 else float("nan")
    mean = float(baseline.mean()) if len(baseline) else float("nan")
    return {"current": current, "baseline_mean": mean, "baseline_std": std,
            "pct_change": (current - mean) / mean * 100 if mean else float("nan"),
            "sigma": (current - mean) / std if std else float("nan")}
