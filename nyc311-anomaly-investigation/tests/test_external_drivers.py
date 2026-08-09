import numpy as np
import pandas as pd
import pytest

from src.analysis.external_drivers import driver_correlations, explain_anomaly
from src.etl.extract_external import build_holiday_calendar


def _frame(effect: float) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    days = pd.date_range("2023-01-01", "2023-09-30", freq="D")
    # hot days occur in both baseline and anomaly windows so the model can learn them
    hot = np.where(days.month.isin([7, 8]), days.day % 2 == 0, days.day % 5 == 0).astype(int)
    base = 100 + 40 * hot + rng.normal(0, 2, len(days))
    anomaly = np.where(days >= pd.Timestamp("2023-07-01"), effect, 0)
    return pd.DataFrame({
        "date_day": days,
        "volume": np.clip(base + anomaly, 1, None).round(),
        "temp_max_f": 70 + 25 * hot,
        "is_hot_day": hot.astype(bool),
        "precip_in": rng.random(len(days)) * 0.2,
        "is_weekend": days.dayofweek >= 5,
        "is_holiday": False,
    })


def test_weather_driven_spike_is_mostly_explained():
    res = explain_anomaly(_frame(0), "2023-07-01", "2023-09-30")
    assert res.pct_explained > 70
    assert abs(res.residual_mean) < 15


def test_unexplained_spike_leaves_large_residual():
    res = explain_anomaly(_frame(120), "2023-07-01", "2023-09-30")
    assert res.pct_explained < 60
    assert res.residual_mean > 50


def test_explain_anomaly_requires_features():
    df = _frame(0)[["date_day", "volume"]]
    with pytest.raises(ValueError):
        explain_anomaly(df, "2023-07-01", "2023-09-30")


def test_driver_correlations_ranks_temperature_first():
    out = driver_correlations(_frame(0))
    assert out.iloc[0]["feature"] in {"temp_max_f", "is_hot_day"}
    assert out["spearman_rho"].abs().max() <= 1


def test_holiday_calendar_is_dense_and_flags_july_fourth():
    cal = build_holiday_calendar("2023-01-01", "2023-12-31")
    assert len(cal) == 365
    assert cal["date_day"].is_unique
    jul4 = cal.loc[cal.date_day == pd.Timestamp("2023-07-04").date()].iloc[0]
    assert bool(jul4.is_holiday)
    jul3 = cal.loc[cal.date_day == pd.Timestamp("2023-07-03").date()].iloc[0]
    assert bool(jul3.is_holiday_eve)


def test_holiday_calendar_accepts_extra_observances():
    cal = build_holiday_calendar("2023-06-01", "2023-06-30",
                                 {"2023-06-15": "Agency system outage"})
    row = cal.loc[cal.date_day == pd.Timestamp("2023-06-15").date()].iloc[0]
    assert row.holiday_name == "Agency system outage"
    assert bool(row.is_holiday)
