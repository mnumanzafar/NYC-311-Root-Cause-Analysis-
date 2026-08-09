"""Cross-check: is the shift a sustained level change or a few extreme days?"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def zscore_flags(series: pd.Series, threshold: float = 3.0) -> pd.DataFrame:
    x = series.astype(float)
    z = (x - x.mean()) / (x.std(ddof=1) or 1.0)
    return pd.DataFrame({"value": x, "zscore": z, "is_anomaly": z.abs() > threshold})


def modified_zscore_flags(series: pd.Series, threshold: float = 3.5) -> pd.DataFrame:
    x = series.astype(float)
    med = x.median()
    mad = (x - med).abs().median() or 1e-9
    z = 0.6745 * (x - med) / mad
    return pd.DataFrame({"value": x, "modified_z": z, "is_anomaly": z.abs() > threshold})


def isolation_forest_flags(frame: pd.DataFrame, features: list[str] | None = None,
                           contamination: float = 0.01,
                           random_state: int = 42) -> pd.DataFrame:
    features = features or list(frame.select_dtypes("number").columns)
    model = IsolationForest(contamination=contamination, random_state=random_state)
    x = frame[features].to_numpy(dtype=float)
    preds = model.fit_predict(x)
    out = frame.copy()
    out["anomaly_score"] = model.score_samples(x)
    out["is_anomaly"] = preds == -1
    return out


def drop_robustness(series: pd.Series, window_start: str, window_end: str,
                    trim: int = 5) -> dict[str, float]:
    """Recompute the window mean after removing the `trim` most extreme days."""
    window = series.loc[window_start:window_end].astype(float)
    trimmed = window.sort_values().iloc[trim:-trim] if len(window) > 2 * trim else window
    baseline = series.drop(window.index).astype(float)
    return {"window_mean": float(window.mean()),
            "window_mean_trimmed": float(trimmed.mean()),
            "baseline_mean": float(baseline.mean()),
            "survives_trimming": bool(
                np.sign(trimmed.mean() - baseline.mean())
                == np.sign(window.mean() - baseline.mean()))}
