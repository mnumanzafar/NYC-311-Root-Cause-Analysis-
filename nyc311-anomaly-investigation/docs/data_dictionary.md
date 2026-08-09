# Data Dictionary

## raw.nyc311_requests
Untouched Socrata extract (`erm2-nwe9`), all columns as text.

## staging.stg_311_requests
| Column | Type | Notes |
|---|---|---|
| request_id | bigint | Source `unique_key`; unique per request |
| created_at / created_date | timestamp / date | Report submission time |
| closed_at | timestamp | Null while open |
| borough | text | Uppercased; nulls exist for geocode failures |
| complaint_type | text | Title-cased; taxonomy changes over time |
| descriptor | text | Sub-category; 'Unspecified' when missing |
| agency | text | Owning agency (NYPD, DSNY, HPD, ...) |
| channel | text | `open_data_channel_type`: phone, online, mobile, unknown |
| resolution_hours | numeric | closed_at - created_at, hours |

## staging.stg_calendar
Dense date spine with year/quarter/month/day-of-year/weekend flags.

## intermediate.int_daily_complaint_volume
Grain: date × borough × complaint_type × channel. Zero-filled via the calendar spine.

## marts.mart_daily_volume_by_borough
Grain: date × borough. Adds 28-day rolling mean/std, rolling z, and 364-day-lag YoY change.

## marts.mart_cohort_breakdown
Grain: borough × complaint_type × channel. Baseline vs. anomaly-window volumes,
absolute/percent change, and each cohort's contribution to the total change.

## External reference data (`data/external/`)
| File | Purpose |
|---|---|
| weather_daily.csv | NOAA daily temp/precip for weather confounder tests |
| us_holidays.csv | Holiday calendar for day-shift effects |
| policy_events.csv | Dated policy/operational changes to align against breakpoints |
