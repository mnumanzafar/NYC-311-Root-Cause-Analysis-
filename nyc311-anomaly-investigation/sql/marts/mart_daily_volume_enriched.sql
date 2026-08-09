-- mart: analysis-ready daily borough series with external drivers attached.
-- Use for confounder elimination: does weather/holiday explain the anomaly?
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_daily_volume_enriched;

CREATE TABLE marts.mart_daily_volume_enriched AS
WITH daily AS (
    SELECT
        date_day,
        borough,
        SUM(volume)              AS volume,
        MAX(temp_max_f)          AS temp_max_f,
        MIN(temp_min_f)          AS temp_min_f,
        AVG(temp_mean_f)         AS temp_mean_f,
        MAX(precip_in)           AS precip_in,
        MAX(snowfall_in)         AS snowfall_in,
        MAX(wind_max_mph)        AS wind_max_mph,
        BOOL_OR(is_hot_day)        AS is_hot_day,
        BOOL_OR(is_freezing_day)   AS is_freezing_day,
        BOOL_OR(is_heavy_rain_day) AS is_heavy_rain_day,
        BOOL_OR(is_snow_day)       AS is_snow_day,
        BOOL_OR(is_high_wind_day)  AS is_high_wind_day,
        BOOL_OR(is_holiday)        AS is_holiday,
        MAX(holiday_name)          AS holiday_name,
        BOOL_OR(is_holiday_eve)    AS is_holiday_eve,
        BOOL_OR(is_day_after_holiday) AS is_day_after_holiday,
        BOOL_OR(is_weekend)        AS is_weekend,
        BOOL_OR(is_non_business_day) AS is_non_business_day
    FROM intermediate.int_daily_volume_enriched
    GROUP BY 1, 2
)
SELECT
    d.*,
    -- lagged weather: complaints often follow the event by a day
    LAG(precip_in)  OVER (PARTITION BY borough ORDER BY date_day) AS precip_in_lag1,
    LAG(temp_max_f) OVER (PARTITION BY borough ORDER BY date_day) AS temp_max_f_lag1,
    -- 3-day heat run, the classic driver of heat/no-hot-water spikes
    (MIN(temp_max_f) OVER (PARTITION BY borough ORDER BY date_day
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) >= 90) AS is_heat_wave_day,
    AVG(volume) OVER w28 AS rolling_mean_28d,
    (volume - AVG(volume) OVER w28)
        / NULLIF(STDDEV_SAMP(volume) OVER w28, 0) AS rolling_z
FROM daily d
WINDOW w28 AS (PARTITION BY borough ORDER BY date_day ROWS BETWEEN 27 PRECEDING AND CURRENT ROW);
