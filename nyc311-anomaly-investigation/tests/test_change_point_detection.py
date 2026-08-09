import numpy as np
import pandas as pd
import pytest

from src.analysis.anomaly_detection import modified_zscore_flags, zscore_flags
from src.analysis.change_point_detection import cusum, rolling_bands, summarize_shift
from src.analysis.seasonality import seasonal_baseline_sigma


@pytest.fixture
def step_series():
    idx = pd.date_range("2023-01-01", periods=200, freq="D")
    rng = np.random.default_rng(7)
    values = np.r_[rng.normal(100, 3, 100), rng.normal(70, 3, 100)]
    return pd.Series(values, index=idx)


def test_cusum_alarms_after_the_shift(step_series):
    result = cusum(step_series, threshold=5.0, baseline_periods=60)
    assert not result["alarm"].iloc[:80].any()
    assert result["alarm"].iloc[120:].any()


def test_summarize_shift_reports_drop(step_series):
    cp = summarize_shift(step_series, pd.Timestamp("2023-04-11"))
    assert cp.pct_change < -20


def test_rolling_bands_shapes(step_series):
    bands = rolling_bands(step_series, window=28, sigma=2.0)
    assert list(bands.columns) == ["value", "mean", "upper", "lower"]
    assert (bands["upper"].dropna() >= bands["lower"].dropna()).all()


def test_zscore_flags_extreme_day():
    s = pd.Series([10.0] * 50 + [500.0], index=pd.date_range("2023-01-01", periods=51))
    assert zscore_flags(s, threshold=3).iloc[-1]["is_anomaly"]
    assert modified_zscore_flags(s).iloc[-1]["is_anomaly"]


def test_seasonal_baseline_sigma_detects_negative_deviation():
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D")
    base = pd.Series(100.0, index=idx)
    base.loc["2023-07-01":"2023-09-30"] = 60.0
    stats_out = seasonal_baseline_sigma(base, "2023-07-01", "2023-09-30", baseline_years=3)
    assert stats_out["pct_change"] < -30
