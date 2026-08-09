-- mart: enriched daily rows tagged with the cohort period they belong to.
-- Grain: date_day x borough x complaint_type (only days inside a cohort window).
-- Powers the Power BI cohort distribution visuals (box/violin, day-of-week profile,
-- overlaid period lines) where a period-level aggregate would hide the spread.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_cohort_daily;

CREATE TABLE marts.mart_cohort_daily AS
WITH daily AS (
    SELECT
        date_day,
        borough,
        complaint_type,
        SUM(volume)                   AS volume,
        AVG(temp_max_f)               AS temp_max_f,
        AVG(temp_mean_f)              AS temp_mean_f,
        MAX(precip_in)                AS precip_in,
        MAX(snowfall_in)              AS snowfall_in,
        MAX(wind_max_mph)             AS wind_max_mph,
        BOOL_OR(is_hot_day)           AS is_hot_day,
        BOOL_OR(is_freezing_day)      AS is_freezing_day,
        BOOL_OR(is_heavy_rain_day)    AS is_heavy_rain_day,
        BOOL_OR(is_snow_day)          AS is_snow_day,
        BOOL_OR(is_high_wind_day)     AS is_high_wind_day,
        BOOL_OR(is_holiday)           AS is_holiday,
        BOOL_OR(is_weekend)           AS is_weekend,
        BOOL_OR(is_non_business_day)  AS is_non_business_day
    FROM intermediate.int_daily_volume_enriched
    GROUP BY 1, 2, 3
),
tagged AS (
    SELECT
        d.*,
        CASE
            WHEN c.in_event_window    THEN 'Post-change'
            WHEN c.in_baseline_window THEN 'Baseline'
        END AS cohort_period,
        c.day_name,
        c.month,
        c.year
    FROM daily d
    JOIN staging.stg_calendar c ON c.date_day = d.date_day
    WHERE c.in_event_window OR c.in_baseline_window
)
SELECT
    t.*,
    -- day index within its own window: lets Power BI overlay the two periods
    -- on a common x-axis even when they differ in calendar dates.
    ROW_NUMBER() OVER (
        PARTITION BY borough, complaint_type, cohort_period ORDER BY date_day
    ) AS day_in_period,
    CASE
        WHEN is_snow_day       THEN 'Snow'
        WHEN is_heavy_rain_day THEN 'Heavy rain'
        WHEN is_high_wind_day  THEN 'High wind'
        WHEN is_hot_day        THEN 'Heat'
        WHEN is_freezing_day   THEN 'Freeze'
        WHEN is_holiday        THEN 'Holiday'
        ELSE 'Normal'
    END AS primary_driver
FROM tagged t;

CREATE INDEX IF NOT EXISTS ix_mcd_period
    ON marts.mart_cohort_daily (cohort_period, borough, complaint_type);
