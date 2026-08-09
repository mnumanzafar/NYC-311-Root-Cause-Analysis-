-- mart: long/unpivoted driver-flag table (date x borough x driver_type).
-- Power BI uses this as a disconnected-ish dimension + overlay source: one slicer
-- ("Driver type") and one ribbon/marker layer instead of ten boolean columns.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_daily_driver_events;

CREATE TABLE marts.mart_daily_driver_events AS
WITH base AS (
    SELECT
        date_day,
        borough,
        is_hot_day, is_freezing_day, is_heavy_rain_day, is_snow_day,
        is_high_wind_day, is_holiday, is_holiday_eve, is_day_after_holiday,
        is_weekend, holiday_name, temp_max_f, precip_in, snowfall_in
    FROM marts.mart_daily_volume_enriched
),
unpivoted AS (
    SELECT date_day, borough, 'Heat'        AS driver_type, 'Weather' AS driver_group,
           'Max temp ' || ROUND(temp_max_f::numeric, 0) || 'F' AS driver_detail
    FROM base WHERE is_hot_day
    UNION ALL
    SELECT date_day, borough, 'Freeze', 'Weather',
           'Max temp ' || ROUND(temp_max_f::numeric, 0) || 'F'
    FROM base WHERE is_freezing_day
    UNION ALL
    SELECT date_day, borough, 'Heavy rain', 'Weather',
           ROUND(precip_in::numeric, 2) || ' in precip'
    FROM base WHERE is_heavy_rain_day
    UNION ALL
    SELECT date_day, borough, 'Snow', 'Weather',
           ROUND(snowfall_in::numeric, 1) || ' in snow'
    FROM base WHERE is_snow_day
    UNION ALL
    SELECT date_day, borough, 'High wind', 'Weather', NULL
    FROM base WHERE is_high_wind_day
    UNION ALL
    SELECT date_day, borough, 'Holiday', 'Calendar', holiday_name
    FROM base WHERE is_holiday
    UNION ALL
    SELECT date_day, borough, 'Holiday eve', 'Calendar', holiday_name
    FROM base WHERE is_holiday_eve
    UNION ALL
    SELECT date_day, borough, 'Day after holiday', 'Calendar', holiday_name
    FROM base WHERE is_day_after_holiday
    UNION ALL
    SELECT date_day, borough, 'Weekend', 'Calendar', NULL
    FROM base WHERE is_weekend
)
SELECT * FROM unpivoted;

CREATE INDEX IF NOT EXISTS ix_mdde_date ON marts.mart_daily_driver_events (date_day);
