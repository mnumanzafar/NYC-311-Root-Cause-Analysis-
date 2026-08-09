"""Smoke-test the BI marts SQL (executed on DuckDB with a synthetic intermediate table).

Guards the Power BI contract: column names, driver labels, and anomaly band math.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> str:
    sql = (ROOT / "sql" / name).read_text()
    # DuckDB has no CREATE INDEX IF NOT EXISTS on the same signature; drop them.
    sql = re.sub(r"CREATE INDEX[^;]+;", "", sql, flags=re.IGNORECASE)
    return sql


@pytest.fixture()
def con():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA intermediate; CREATE SCHEMA marts;")
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
    d0 = dt.date(2023, 6, 1)
    for i in range(60):
        day = d0 + dt.timedelta(days=i)
        hot = i == 40
        vol = 400 if not hot else 1200
        for borough in ("BROOKLYN", "QUEENS"):
            rows.append(
                (
                    day, borough, "HEAT/HOT WATER", "PHONE", vol,
                    95.0 if hot else 72.0, 60.0, 70.0, 0.0, 0.0, 10.0,
                    hot, False, False, False, False, i == 10,
                    "Test Holiday" if i == 10 else None, False, False,
                    day.weekday() >= 5, day.weekday() >= 5,
                )
            )
    c.executemany(
        "INSERT INTO intermediate.int_daily_volume_enriched VALUES ("
        + ",".join(["?"] * 22)
        + ")",
        rows,
    )
    return c


def test_enriched_by_type_mart_shape(con):
    con.execute(_load("marts/mart_daily_volume_enriched_by_type.sql"))
    cols = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'mart_daily_volume_enriched_by_type'"
        ).fetchall()
    }
    for required in {
        "date_day", "borough", "complaint_type", "volume", "rolling_mean_28d",
        "rolling_sigma_28d", "rolling_z", "band_upper_2s", "band_lower_2s",
        "primary_driver", "precip_in_lag1", "temp_max_f_lag1",
    }:
        assert required in cols, required

    n = con.execute(
        "SELECT COUNT(*) FROM marts.mart_daily_volume_enriched_by_type"
    ).fetchone()[0]
    assert n == 120  # 60 days x 2 boroughs x 1 type

    assert con.execute(
        "SELECT MIN(band_lower_2s) FROM marts.mart_daily_volume_enriched_by_type"
    ).fetchone()[0] >= 0


def test_spike_day_is_flagged_and_labelled(con):
    con.execute(_load("marts/mart_daily_volume_enriched_by_type.sql"))
    z, driver = con.execute(
        """
        SELECT rolling_z, primary_driver
        FROM marts.mart_daily_volume_enriched_by_type
        WHERE borough = 'BROOKLYN' AND date_day = DATE '2023-07-11'
        """
    ).fetchone()
    assert z > 2
    assert driver == "Heat"


def test_driver_events_unpivot(con):
    con.execute(_load("marts/mart_daily_volume_enriched.sql"))
    con.execute(_load("marts/mart_daily_driver_events.sql"))
    types = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT driver_type FROM marts.mart_daily_driver_events"
        ).fetchall()
    }
    assert {"Heat", "Holiday", "Weekend"} <= types
    groups = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT driver_group FROM marts.mart_daily_driver_events"
        ).fetchall()
    }
    assert groups == {"Weather", "Calendar"}

    # one Heat row per borough on the spike day, and no rows on ordinary days
    assert con.execute(
        "SELECT COUNT(*) FROM marts.mart_daily_driver_events WHERE driver_type = 'Heat'"
    ).fetchone()[0] == 2
    assert con.execute(
        "SELECT COUNT(*) FROM marts.mart_daily_driver_events "
        "WHERE date_day = DATE '2023-06-02' AND driver_group = 'Weather'"
    ).fetchone()[0] == 0
