# External Enrichment Pipeline

Joins **daily weather** and **holiday indicators** onto the complaint-volume mart so the
investigation can separate weather/calendar effects from the real root cause.

## Flow

```text
Open-Meteo ERA5 archive ─┐
                         ├─> data/raw/*.parquet ─> raw.weather_daily
holidays (US/NY) + extra ┘                        raw.holidays_daily
                                                       |
                     staging.stg_weather_daily / staging.stg_holidays_daily
                                                       |
                   intermediate.int_daily_volume_enriched  (LEFT JOIN on date + borough)
                                                       |
                        marts.mart_daily_volume_enriched  (borough-day + drivers)
```

## Run it

```bash
make external      # extract -> load -> rebuild sql layers
# or step by step
python -m src.etl.extract_external
python -m src.etl.load_external
python -m src.etl.run_sql_pipeline
```

## Sources

| Source | Endpoint / package | Key needed | Grain |
| --- | --- | --- | --- |
| Weather | `https://archive-api.open-meteo.com/v1/archive` | no | borough x day |
| Holidays | `holidays` (country `US`, subdiv `NY`) | no | day |

Station coordinates, thresholds, and any extra observances (agency closures, local
events) live in `config/config.yaml` under `external:`.

## Join semantics

- All joins are `LEFT JOIN` — enrichment gaps never drop complaint rows.
- Weather joins on `date_day + UPPER(borough)`; if a borough station is missing, it
  falls back to the **citywide daily average**.
- The holiday calendar is dense (one row per day), so flags are never NULL.
- `weather_missing` / `holiday_calendar_missing` columns expose coverage gaps for QA.

## Derived driver flags

`is_hot_day` (tmax >= 90F), `is_freezing_day` (tmin <= 32F), `is_heavy_rain_day`
(>= 1.0in), `is_snow_day`, `is_high_wind_day` (>= 30mph), `is_heat_wave_day`
(3 consecutive days >= 90F), plus `is_holiday`, `holiday_name`, `is_holiday_eve`,
`is_day_after_holiday`, `is_weekend`, `is_non_business_day`, and 1-day lags of
precipitation and max temperature.

## Confounder elimination

`src/analysis/external_drivers.py`:

- `explain_anomaly(df, start, end)` fits a Poisson driver-only baseline on the
  pre-anomaly period and returns `pct_explained` plus the residual gap. High
  `pct_explained` = weather/calendar story; low = look elsewhere (policy, campaign,
  pipeline change).
- `driver_correlations(df)` ranks drivers by Spearman correlation with daily volume.

Covered by `tests/test_external_drivers.py`.
