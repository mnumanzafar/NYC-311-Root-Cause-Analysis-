"""Quantify how much of a volume anomaly external drivers (weather, holidays) explain.

Used in the "eliminate confounders" step: fit a driver-only baseline model on the
pre-anomaly period, predict the anomaly window, and report the residual gap.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from sklearn.linear_model import PoissonRegressor

DEFAULT_FEATURES = [
    "temp_max_f", "temp_min_f", "precip_in", "snowfall_in", "wind_max_mph",
    "is_hot_day", "is_heavy_rain_day", "is_snow_day",
    "is_holiday", "is_holiday_eve", "is_weekend",
]


@dataclass
class ExplainedVariance:
    actual_mean: float
    expected_mean: float
    residual_mean: float
    pct_explained: float
    n_baseline: int
    n_anomaly: int

    def to_dict(self) -> dict:
        return asdict(self)


def _matrix(df: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = df[features].copy()
    for col in x.columns:
        if x[col].dtype == bool:
            x[col] = x[col].astype(int)
    return x.astype(float).fillna(x.astype(float).mean()).to_numpy()


def explain_anomaly(
    df: pd.DataFrame,
    anomaly_start: str,
    anomaly_end: str,
    value_col: str = "volume",
    date_col: str = "date_day",
    features: list[str] | None = None,
) -> ExplainedVariance:
    """Fit drivers on pre-anomaly data, predict the window, return the unexplained gap.

    pct_explained near 100 means weather/holidays account for the move; near 0 means
    the driver is something else (policy, campaign, data pipeline, real deterioration).
    """
    features = [f for f in (features or DEFAULT_FEATURES) if f in df.columns]
    if not features:
        raise ValueError("no enrichment features present — run the external pipeline first")

    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    start, end = pd.Timestamp(anomaly_start), pd.Timestamp(anomaly_end)

    baseline = d[d[date_col] < start]
    anomaly = d[(d[date_col] >= start) & (d[date_col] <= end)]
    if baseline.empty or anomaly.empty:
        raise ValueError("baseline or anomaly window is empty")

    model = PoissonRegressor(alpha=1e-6, max_iter=1000)
    model.fit(_matrix(baseline, features), baseline[value_col].astype(float))

    expected = model.predict(_matrix(anomaly, features))
    baseline_level = float(baseline[value_col].mean())
    actual_mean = float(anomaly[value_col].mean())
    expected_mean = float(np.mean(expected))

    observed_shift = actual_mean - baseline_level
    explained_shift = expected_mean - baseline_level
    pct = 100.0 * explained_shift / observed_shift if observed_shift else 0.0

    return ExplainedVariance(
        actual_mean=actual_mean,
        expected_mean=expected_mean,
        residual_mean=actual_mean - expected_mean,
        pct_explained=float(np.clip(pct, -100.0, 100.0)),
        n_baseline=len(baseline),
        n_anomaly=len(anomaly),
    )


def driver_correlations(df: pd.DataFrame, value_col: str = "volume",
                        features: list[str] | None = None) -> pd.DataFrame:
    """Spearman correlation of each external driver with daily volume."""
    features = [f for f in (features or DEFAULT_FEATURES) if f in df.columns]
    rows = []
    for f in features:
        s = df[f].astype(float) if df[f].dtype != bool else df[f].astype(int)
        rows.append({"feature": f, "spearman_rho": s.corr(df[value_col].astype(float),
                                                          method="spearman")})
    return (pd.DataFrame(rows)
            .assign(abs_rho=lambda t: t.spearman_rho.abs())
            .sort_values("abs_rho", ascending=False)
            .drop(columns="abs_rho")
            .reset_index(drop=True))
