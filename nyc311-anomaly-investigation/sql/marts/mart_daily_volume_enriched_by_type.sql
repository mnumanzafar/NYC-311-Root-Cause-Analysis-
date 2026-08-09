-- mart: BI-facing fact at date x borough x complaint_type grain, with external drivers.
-- Powers the Power BI "Enriched Daily Volume" page and its borough/category drilldowns.
-- The borough-grain mart (mart_daily_volume_enriched) stays the modelling table;
-- this one exists so Power BI can drill without re-aggregating raw request rows.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_daily_volume_enriched_by_type;

CREATE TABLE marts.mart_daily_volume_enriched_by_type AS
WITH daily AS (
    SELECT
        date_day,
        borough,
        complaint_type,
        SUM(volume)                   AS volume,
        AVG(temp_max_f)               AS temp_max_f,
        AVG(temp_min_f)               AS temp_min_f,
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
        MAX(holiday_name)             AS holiday_name,
        BOOL_OR(is_holiday_eve)       AS is_holiday_eve,
        BOOL_OR(is_day_after_holiday) AS is_day_after_holiday,
        BOOL_OR(is_weekend)           AS is_weekend,
        BOOL_OR(is_non_business_day)  AS is_non_business_day
    FROM intermediate.int_daily_volume_enriched
    GROUP BY 1, 2, 3
),
windowed AS (
    SELECT
        d.*,
        LAG(precip_in)  OVER p AS precip_in_lag1,
        LAG(temp_max_f) OVER p AS temp_max_f_lag1,
        AVG(volume)         OVER w28 AS rolling_mean_28d,
        STDDEV_SAMP(volume) OVER w28 AS rolling_sigma_28d
    FROM daily d
    WINDOW
        p   AS (PARTITION BY borough, complaint_type ORDER BY date_day),
        w28 AS (PARTITION BY borough, complaint_type ORDER BY date_day
                ROWS BETWEEN 27 PRECEDING AND CURRENT ROW)
)
SELECT
    w.*,
    (volume - rolling_mean_28d) / NULLIF(rolling_sigma_28d, 0) AS rolling_z,
    rolling_mean_28d + 2 * rolling_sigma_28d AS band_upper_2s,
    GREATEST(rolling_mean_28d - 2 * rolling_sigma_28d, 0) AS band_lower_2s,
    -- single categorical driver label so one slicer covers all overlays
    CASE
        WHEN is_snow_day       THEN 'Snow'
        WHEN is_heavy_rain_day THEN 'Heavy rain'
        WHEN is_high_wind_day  THEN 'High wind'
        WHEN is_hot_day        THEN 'Heat'
        WHEN is_freezing_day   THEN 'Freeze'
        WHEN is_holiday        THEN 'Holiday'
        ELSE 'Normal'
    END AS primary_driver
FROM windowed w;

CREATE INDEX IF NOT EXISTS ix_mdvebt_date
    ON marts.mart_daily_volume_enriched_by_type (date_day);
CREATE INDEX IF NOT EXISTS ix_mdvebt_bor_type
    ON marts.mart_daily_volume_enriched_by_type (borough, complaint_type);
