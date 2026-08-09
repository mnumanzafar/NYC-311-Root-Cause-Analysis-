"""Contract tests for the cohort-comparison BI marts (run on DuckDB).

Synthetic data: two boroughs x two complaint types, a 30-day baseline window and a
30-day post-change window. One complaint type doubles in the post period; the other
is flat. The marts must localise the change to the right cohort.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]

BASELINE_START = dt.date(2023, 6, 1)
POST_START = dt.date(2023, 7, 1)
WINDOW_DAYS = 30


def _load(name: str) -> str:
    sql = (ROOT / "sql" / name).read_text()
    return re.sub(r"CREATE INDEX[^;]+;", "", sql, flags=re.IGNORECASE)


@pytest.fixture()
def con():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA intermediate; CREATE SCHEMA staging; CREATE SCHEMA marts;")
    c.execute(
        """
        CREATE TABLE intermediate.int_daily_volume_enriched (
            date_day DATE, borough VARCHAR, complaint_type VARCHAR, channel VARCHAR,
            volume BIGINT, temp_max_f DOUBLE, temp_min_f DOUBLE, temp_mean_f DOUBLE,
            precip_in DOUBLE, snowfall_in DOUBLE, wind_max_mph DOUBLE,
            is_hot_day BOOLEAN, is_freezing_day BOOLEAN, is_heavy_rain_day BOOLEAN,
            is_snow_day BOOLEAN, is_high_wind_day BOOLEAN, is_holiday BOOLEAN,
            holiday_name VARCHAR, is_holiday_eve BOOLEAN, is_day_after_holiday BOOLEAN,
            is_weekend BOOLEAN, is_non_business_day BOOLEAN
        )
        """
    )
    rows = []
    for start, period in ((BASELINE_START, "base"), (POST_START, "post")):
        for i in range(WINDOW_DAYS):
            day = start + dt.timedelta(days=i)
            hot = period == "post" and i % 10 == 0
            for borough in ("BROOKLYN", "QUEENS"):
                for ctype, base_vol in (("HEAT/HOT WATER", 200), ("NOISE", 300)):
                    vol = base_vol
                    if ctype == "HEAT/HOT WATER" and period == "post":
                        vol = base_vol * 2
                    rows.append(
                        (
                            day, borough, ctype, "PHONE", vol,
                            95.0 if hot else 72.0, 60.0, 70.0, 0.0, 0.0, 10.0,
                            hot, False, False, False, False, False,
                            None, False, False,
                            day.weekday() >= 5, day.weekday() >= 5,
                        )
                    )
    c.executemany(
        "INSERT INTO intermediate.int_daily_volume_enriched VALUES ("
        + ",".join(["?"] * 22) + ")",
        rows,
    )
    c.execute(
        """
        CREATE TABLE staging.stg_calendar AS
        SELECT
            d::date AS date_day,
            EXTRACT(YEAR FROM d)::int AS year,
            EXTRACT(MONTH FROM d)::int AS month,
            strftime(d, '%a') AS day_name,
            EXTRACT(ISODOW FROM d) IN (6, 7) AS is_weekend,
            (d::date BETWEEN DATE '2023-07-01' AND DATE '2023-07-30') AS in_event_window,
            (d::date BETWEEN DATE '2023-06-01' AND DATE '2023-06-30') AS in_baseline_window
        FROM GENERATE_SERIES(DATE '2023-06-01', DATE '2023-07-30', INTERVAL '1 day') AS t(d)
        """
    )
    return c


@pytest.fixture()
def marts(con):
    con.execute(_load("marts/mart_cohort_daily.sql"))
    con.execute(_load("marts/mart_cohort_comparison.sql"))
    return con


def test_cohort_daily_covers_only_window_days(marts):
    periods = {
        r[0]
        for r in marts.execute(
            "SELECT DISTINCT cohort_period FROM marts.mart_cohort_daily"
        ).fetchall()
    }
    assert periods == {"Baseline", "Post-change"}

    n = marts.execute("SELECT COUNT(*) FROM marts.mart_cohort_daily").fetchone()[0]
    assert n == WINDOW_DAYS * 2 * 2 * 2  # days x periods x boroughs x types

    # day_in_period restarts at 1 for each period so the two windows can overlay
    assert marts.execute(
        "SELECT MIN(day_in_period), MAX(day_in_period) FROM marts.mart_cohort_daily"
    ).fetchone() == (1, WINDOW_DAYS)


def test_change_is_localised_to_the_right_cohort(marts):
    rows = dict(
        marts.execute(
            "SELECT complaint_type, SUM(abs_change) FROM marts.mart_cohort_comparison "
            "GROUP BY 1"
        ).fetchall()
    )
    assert rows["HEAT/HOT WATER"] == pytest.approx(200 * WINDOW_DAYS * 2)
    assert rows["NOISE"] == pytest.approx(0.0)


def test_pct_change_and_contribution(marts):
    pct, contrib = marts.execute(
        """
        SELECT pct_change, contribution_pct
        FROM marts.mart_cohort_comparison
        WHERE borough = 'BROOKLYN' AND complaint_type = 'HEAT/HOT WATER'
        """
    ).fetchone()
    assert pct == pytest.approx(100.0)
    # two boroughs move identically -> each carries half of the citywide change
    assert contrib == pytest.approx(50.0)

    total = marts.execute(
        "SELECT SUM(contribution_pct) FROM marts.mart_cohort_comparison"
    ).fetchone()[0]
    assert total == pytest.approx(100.0)


def test_length_normalised_baseline(marts):
    baseline_scaled, baseline_volume, base_days, post_days = marts.execute(
        """
        SELECT baseline_volume_scaled, baseline_volume, baseline_days, post_days
        FROM marts.mart_cohort_comparison
        WHERE borough = 'QUEENS' AND complaint_type = 'NOISE'
        """
    ).fetchone()
    assert base_days == post_days == WINDOW_DAYS
    # equal windows -> scaling is a no-op
    assert baseline_scaled == pytest.approx(float(baseline_volume))


def test_driver_and_weather_deltas_exposed(marts):
    row = marts.execute(
        """
        SELECT temp_max_f_delta, post_driver_day_pct, baseline_driver_day_pct,
               calendar_mix_warning
        FROM marts.mart_cohort_comparison
        WHERE borough = 'BROOKLYN' AND complaint_type = 'NOISE'
        """
    ).fetchone()
    temp_delta, post_driver_pct, base_driver_pct, mix_warning = row
    assert temp_delta > 0            # post window contains hot days
    assert post_driver_pct > base_driver_pct == 0
    assert mix_warning is False      # weekend mix is identical across windows


def test_effect_size_sign_and_magnitude(marts):
    d_heat, d_noise = marts.execute(
        """
        SELECT
            MAX(effect_size_d) FILTER (WHERE complaint_type = 'HEAT/HOT WATER'),
            MAX(COALESCE(effect_size_d, 0)) FILTER (WHERE complaint_type = 'NOISE')
        FROM marts.mart_cohort_comparison
        """
    ).fetchone()
    assert d_heat is None or d_heat > 0 or d_heat != d_heat  # flat sigma -> may be NULL
    assert d_noise == pytest.approx(0.0)


def test_measures_reference_existing_columns():
    dax = (ROOT / "powerbi" / "measures.dax").read_text()
    for measure in (
        "Cohort Delta", "Cohort Delta %", "Cohort Contribution %",
        "Cohort Effect Size d", "Cohort Welch t", "Cohort Verdict",
        "Cohort Delta | Weather Adjusted", "Baseline Volume | Scaled",
    ):
        assert f"\n{measure} =" in dax, measure

    pq = (ROOT / "powerbi" / "queries.pq").read_text()
    for query in ("CohortCompare", "CohortDaily", "DimPeriod"):
        assert f"Query name: {query}" in pq, query
