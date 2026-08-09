import numpy as np
import pandas as pd
import pytest

from src.reporting import cohort_export as ce


@pytest.fixture
def daily():
    rng = np.random.default_rng(7)
    rows = []
    for borough, base, post in [("BROOKLYN", 100, 160), ("QUEENS", 80, 82)]:
        for i in range(30):
            rows.append({"date_day": pd.Timestamp("2023-01-01") + pd.Timedelta(days=i),
                         "borough": borough, "complaint_type": "Heat",
                         "cohort_period": "Baseline",
                         "volume": base + rng.normal(0, 5)})
            rows.append({"date_day": pd.Timestamp("2023-07-01") + pd.Timedelta(days=i),
                         "borough": borough, "complaint_type": "Heat",
                         "cohort_period": "Post-change",
                         "volume": post + rng.normal(0, 5)})
    return pd.DataFrame(rows)


@pytest.fixture
def comparison():
    return pd.DataFrame([
        {"borough": "BROOKLYN", "complaint_type": "Heat", "baseline_days": 30,
         "post_days": 30, "baseline_volume": 3000, "post_volume": 4800,
         "baseline_daily_avg": 100.0, "post_daily_avg": 160.0,
         "baseline_volume_scaled": 3000.0, "abs_change": 1800.0,
         "pct_change": 60.0, "contribution_pct": 96.8, "effect_size_d": 1.8,
         "temp_max_f_delta": 12.0, "precip_in_delta": -0.2,
         "baseline_driver_day_pct": 5.0, "post_driver_day_pct": 40.0,
         "calendar_mix_warning": False},
        {"borough": "QUEENS", "complaint_type": "Heat", "baseline_days": 30,
         "post_days": 30, "baseline_volume": 2400, "post_volume": 2460,
         "baseline_daily_avg": 80.0, "post_daily_avg": 82.0,
         "baseline_volume_scaled": 2400.0, "abs_change": 60.0,
         "pct_change": 2.5, "contribution_pct": 3.2, "effect_size_d": 0.1,
         "temp_max_f_delta": 1.0, "precip_in_delta": 0.0,
         "baseline_driver_day_pct": 5.0, "post_driver_day_pct": 6.0,
         "calendar_mix_warning": True},
    ])


def test_bh_q_values_are_monotone_and_bounded():
    q = ce.benjamini_hochberg_q([0.001, 0.02, 0.5, np.nan])
    assert np.isnan(q[3])
    assert q[0] <= q[1] <= q[2] <= 1.0
    assert q[0] >= 0.001


def test_significance_detects_real_shift_only(daily):
    sig = ce.cohort_significance(daily).set_index("borough")
    assert sig.loc["BROOKLYN", "p_value"] < 0.001
    assert sig.loc["QUEENS", "p_value"] > 0.05


def test_export_frame_contract(comparison, daily):
    df = ce.build_export_frame(comparison, daily, alpha=0.01)
    assert list(df.columns) == ce.EXPORT_COLUMNS
    assert df.iloc[0]["borough"] == "BROOKLYN"  # ranked by |contribution|
    assert bool(df.iloc[0]["is_significant"]) is True
    assert bool(df.iloc[1]["is_significant"]) is False
    assert df.iloc[0]["driver_day_pct_delta"] == pytest.approx(35.0)


def test_export_frame_without_daily_still_exports(comparison):
    df = ce.build_export_frame(comparison, None)
    assert df["p_value"].isna().all()
    assert not df["is_significant"].any()


def test_csv_roundtrip(comparison, daily, tmp_path):
    df = ce.build_export_frame(comparison, daily)
    path = ce.export_csv(df, tmp_path / "out.csv")
    back = pd.read_csv(path)
    assert list(back.columns) == ce.EXPORT_COLUMNS
    assert len(back) == 2


def test_pdf_is_written(comparison, daily, tmp_path):
    df = ce.build_export_frame(comparison, daily)
    path = ce.export_pdf(df, tmp_path / "out.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 2000


def test_run_from_parquet(comparison, daily, tmp_path):
    (tmp_path / "marts").mkdir()
    comparison.to_parquet(tmp_path / "marts" / "mart_cohort_comparison.parquet")
    daily.to_parquet(tmp_path / "marts" / "mart_cohort_daily.parquet")
    outcome = ce.run(out_dir=tmp_path / "out", from_parquet=tmp_path / "marts",
                     stem="cohorts")
    written = outcome["files"]
    assert written["csv"].exists() and written["pdf"].exists()
    assert written["narrative"].exists()


def test_summary_counts(comparison, daily):
    df = ce.build_export_frame(comparison, daily)
    s = ce.summarise(df)
    assert s["cohorts"] == 2 and s["mix_warnings"] == 1
    assert s["total_abs_change"] == pytest.approx(1860.0)
