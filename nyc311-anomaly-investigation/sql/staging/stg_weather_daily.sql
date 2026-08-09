-- staging: clean daily weather observations, one row per borough per day.
CREATE SCHEMA IF NOT EXISTS staging;
DROP TABLE IF EXISTS staging.stg_weather_daily;

CREATE TABLE staging.stg_weather_daily AS
SELECT
    date_day::date                        AS date_day,
    UPPER(TRIM(borough))                  AS borough,
    station_name,
    temperature_2m_max::numeric           AS temp_max_f,
    temperature_2m_min::numeric           AS temp_min_f,
    temperature_2m_mean::numeric          AS temp_mean_f,
    precipitation_sum::numeric            AS precip_in,
    rain_sum::numeric                     AS rain_in,
    snowfall_sum::numeric                 AS snowfall_in,
    wind_speed_10m_max::numeric           AS wind_max_mph,
    -- driver flags used by hypothesis tests / confounder elimination
    (temperature_2m_max::numeric >= 90)   AS is_hot_day,
    (temperature_2m_min::numeric <= 32)   AS is_freezing_day,
    (precipitation_sum::numeric >= 1.0)   AS is_heavy_rain_day,
    (snowfall_sum::numeric > 0)           AS is_snow_day,
    (wind_speed_10m_max::numeric >= 30)   AS is_high_wind_day
FROM raw.weather_daily
WHERE date_day IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_stg_weather_day_boro
    ON staging.stg_weather_daily (date_day, borough);
