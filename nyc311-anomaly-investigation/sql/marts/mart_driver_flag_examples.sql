-- mart_driver_flag_examples.sql
-- Drillthrough target feed for Power BI: click a significant driver flag and land
-- on the exact borough / complaint-category / day breakdown behind it, plus the
-- example complaint types that carry most of the excess volume.
--
-- Grain: driver_flag x borough x complaint_type x date_day  (only driver-days)
-- Reads marts.mart_daily_volume_enriched_by_type, so build it after that mart.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_driver_flag_examples;

CREATE TABLE marts.mart_driver_flag_examples AS
WITH base AS (
    SELECT date_day, borough, complaint_type, volume,
           rolling_mean_28d, rolling_sigma_28d, rolling_z, band_upper_2s,
           primary_driver, temp_max_f, precip_in, snowfall_in, wind_max_mph,
           holiday_name,
           is_hot_day, is_freezing_day, is_heavy_rain_day, is_snow_day,
           is_high_wind_day, is_holiday, is_holiday_eve, is_day_after_holiday,
           is_weekend, is_non_business_day
    FROM marts.mart_daily_volume_enriched_by_type
),
unpivoted AS (
    SELECT b.date_day, b.borough, b.complaint_type, b.volume,
           b.rolling_mean_28d, b.rolling_sigma_28d, b.rolling_z, b.band_upper_2s,
           b.primary_driver, b.temp_max_f, b.precip_in, b.snowfall_in,
           b.wind_max_mph, b.holiday_name,
           f.driver_flag, f.driver_group, f.driver_label
    FROM base b
    CROSS JOIN LATERAL (
        VALUES
            ('is_hot_day',           'Weather',  'Hot day (>= 90F)',            b.is_hot_day),
            ('is_freezing_day',      'Weather',  'Freezing day (<= 32F)',       b.is_freezing_day),
            ('is_heavy_rain_day',    'Weather',  'Heavy rain (>= 1.0 in)',      b.is_heavy_rain_day),
            ('is_snow_day',          'Weather',  'Snow day',                    b.is_snow_day),
            ('is_high_wind_day',     'Weather',  'High wind (>= 30 mph)',       b.is_high_wind_day),
            ('is_holiday',           'Calendar', 'Public holiday',              b.is_holiday),
            ('is_holiday_eve',       'Calendar', 'Holiday eve',                 b.is_holiday_eve),
            ('is_day_after_holiday', 'Calendar', 'Day after holiday',           b.is_day_after_holiday),
            ('is_weekend',           'Calendar', 'Weekend',                     b.is_weekend),
            ('is_non_business_day',  'Calendar', 'Non-business day',            b.is_non_business_day)
    ) AS f(driver_flag, driver_group, driver_label, flag_value)
    WHERE f.flag_value
),
scored AS (
    SELECT u.*,
           u.volume - u.rolling_mean_28d AS excess_vs_baseline,
           CASE WHEN u.rolling_mean_28d > 0
                THEN 100.0 * (u.volume - u.rolling_mean_28d) / u.rolling_mean_28d
           END                            AS excess_pct,
           (u.rolling_z IS NOT NULL AND u.rolling_z >= 2) AS is_anomaly_day
    FROM unpivoted u
),
ranked AS (
    SELECT s.*,
           SUM(excess_vs_baseline) OVER cohort AS cohort_excess_total,
           COUNT(*)                OVER cohort AS cohort_driver_days,
           AVG(rolling_z)          OVER cohort AS cohort_avg_z,
           SUM(CASE WHEN is_anomaly_day THEN 1 ELSE 0 END)
                                   OVER cohort AS cohort_anomaly_days
    FROM scored s
    WINDOW cohort AS (PARTITION BY driver_flag, borough, complaint_type)
)
SELECT
    driver_flag,
    driver_group,
    driver_label,
    date_day,
    borough,
    complaint_type,
    volume,
    rolling_mean_28d,
    rolling_z,
    band_upper_2s,
    excess_vs_baseline,
    excess_pct,
    is_anomaly_day,
    primary_driver,
    temp_max_f,
    precip_in,
    snowfall_in,
    wind_max_mph,
    holiday_name,
    cohort_driver_days,
    cohort_anomaly_days,
    cohort_excess_total,
    cohort_avg_z,
    -- "top example complaint types" ranking, precomputed so DAX stays simple
    DENSE_RANK() OVER (PARTITION BY driver_flag, borough
                       ORDER BY cohort_excess_total DESC, complaint_type)          AS example_rank,
    DENSE_RANK() OVER (PARTITION BY driver_flag
                       ORDER BY cohort_excess_total DESC, borough, complaint_type) AS example_rank_citywide
FROM ranked;

CREATE INDEX IF NOT EXISTS ix_driver_examples_flag
    ON marts.mart_driver_flag_examples (driver_flag, borough, complaint_type);
CREATE INDEX IF NOT EXISTS ix_driver_examples_date
    ON marts.mart_driver_flag_examples (date_day);
