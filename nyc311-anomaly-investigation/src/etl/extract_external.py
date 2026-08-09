"""Pull external drivers (daily weather + public holidays) into data/raw/.

Weather : Open-Meteo ERA5 archive API (no API key required).
Holidays: `holidays` package (US federal) + NYC-specific observances.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from ..utils.config_loader import ROOT, load_config, setup_logging

log = logging.getLogger(__name__)

WEATHER_DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
]


def fetch_weather(lat: float, lon: float, start: str, end: str,
                  url: str, timezone: str = "America/New_York") -> pd.DataFrame:
    resp = requests.get(
        url,
        params={
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": end,
            "daily": ",".join(WEATHER_DAILY_VARS),
            "timezone": timezone,
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "wind_speed_unit": "mph",
        },
        timeout=120,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    df = pd.DataFrame(daily).rename(columns={"time": "date_day"})
    df["date_day"] = pd.to_datetime(df["date_day"]).dt.date
    return df


def extract_weather(out_path: Path | None = None) -> Path:
    cfg = load_config()
    ext, an = cfg["external"], cfg["analysis"]
    frames = []
    for station in ext["weather"]["stations"]:
        df = fetch_weather(station["lat"], station["lon"],
                           an["date_start"], an["date_end"],
                           ext["weather"]["archive_url"])
        df.insert(0, "borough", station["borough"])
        df.insert(1, "station_name", station["name"])
        frames.append(df)
        log.info("weather: %s rows for %s", len(df), station["borough"])

    out = pd.concat(frames, ignore_index=True)
    out_path = out_path or ROOT / "data" / "raw" / "weather_daily.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    log.info("wrote %s weather rows -> %s", len(out), out_path)
    return out_path


def build_holiday_calendar(start: str, end: str,
                           extra: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per calendar day with holiday flags (never sparse — safe to LEFT JOIN)."""
    import holidays as pyholidays

    days = pd.date_range(start, end, freq="D")
    us = pyholidays.country_holidays("US", subdiv="NY",
                                     years=range(days[0].year, days[-1].year + 1))
    named = {pd.Timestamp(d).date(): n for d, n in us.items()}
    named.update({pd.Timestamp(d).date(): n for d, n in (extra or {}).items()})

    holiday_dates = set(named)
    rows = []
    for ts in days:
        d: date = ts.date()
        rows.append({
            "date_day": d,
            "is_holiday": d in holiday_dates,
            "holiday_name": named.get(d),
            "is_holiday_eve": (ts + pd.Timedelta(days=1)).date() in holiday_dates,
            "is_day_after_holiday": (ts - pd.Timedelta(days=1)).date() in holiday_dates,
            "is_weekend": ts.dayofweek >= 5,
        })
    return pd.DataFrame(rows)


def extract_holidays(out_path: Path | None = None) -> Path:
    cfg = load_config()
    an = cfg["analysis"]
    extra = cfg["external"].get("holidays", {}).get("extra_observances") or {}
    df = build_holiday_calendar(an["date_start"], an["date_end"], extra)
    out_path = out_path or ROOT / "data" / "raw" / "holidays_daily.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    log.info("wrote %s holiday-calendar rows -> %s", len(df), out_path)
    return out_path


if __name__ == "__main__":
    setup_logging()
    extract_weather()
    extract_holidays()
