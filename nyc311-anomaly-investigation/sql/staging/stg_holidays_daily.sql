-- staging: dense daily holiday calendar (one row per day, no gaps).
CREATE SCHEMA IF NOT EXISTS staging;
DROP TABLE IF EXISTS staging.stg_holidays_daily;

CREATE TABLE staging.stg_holidays_daily AS
SELECT
    date_day::date                       AS date_day,
    COALESCE(is_holiday, FALSE)          AS is_holiday,
    NULLIF(TRIM(holiday_name), '')       AS holiday_name,
    COALESCE(is_holiday_eve, FALSE)      AS is_holiday_eve,
    COALESCE(is_day_after_holiday, FALSE) AS is_day_after_holiday,
    COALESCE(is_weekend, FALSE)          AS is_weekend,
    (COALESCE(is_holiday, FALSE) OR COALESCE(is_weekend, FALSE)) AS is_non_business_day
FROM raw.holidays_daily
WHERE date_day IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_stg_holidays_day
    ON staging.stg_holidays_daily (date_day);
