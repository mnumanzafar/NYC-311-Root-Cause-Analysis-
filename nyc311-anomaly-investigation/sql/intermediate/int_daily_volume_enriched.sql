-- intermediate: complaint volume joined to external drivers (weather + holidays).
-- LEFT JOINs only: enrichment gaps never drop complaint rows.
CREATE SCHEMA IF NOT EXISTS intermediate;
DROP TABLE IF EXISTS intermediate.int_daily_volume_enriched;

CREATE TABLE intermediate.int_daily_volume_enriched AS
SELECT
    v.date_day,
    v.borough,
    v.complaint_type,
    v.channel,
    v.volume,
    -- weather (borough-level station, falls back to citywide average)
    COALESCE(w.temp_max_f,  cw.temp_max_f)   AS temp_max_f,
    COALESCE(w.temp_min_f,  cw.temp_min_f)   AS temp_min_f,
    COALESCE(w.temp_mean_f, cw.temp_mean_f)  AS temp_mean_f,
    COALESCE(w.precip_in,   cw.precip_in)    AS precip_in,
    COALESCE(w.snowfall_in, cw.snowfall_in)  AS snowfall_in,
    COALESCE(w.wind_max_mph, cw.wind_max_mph) AS wind_max_mph,
    COALESCE(w.is_hot_day, FALSE)            AS is_hot_day,
    COALESCE(w.is_freezing_day, FALSE)       AS is_freezing_day,
    COALESCE(w.is_heavy_rain_day, FALSE)     AS is_heavy_rain_day,
    COALESCE(w.is_snow_day, FALSE)           AS is_snow_day,
    COALESCE(w.is_high_wind_day, FALSE)      AS is_high_wind_day,
    (w.date_day IS NULL AND cw.date_day IS NULL) AS weather_missing,
    -- holiday calendar
    COALESCE(h.is_holiday, FALSE)            AS is_holiday,
    h.holiday_name,
    COALESCE(h.is_holiday_eve, FALSE)        AS is_holiday_eve,
    COALESCE(h.is_day_after_holiday, FALSE)  AS is_day_after_holiday,
    COALESCE(h.is_weekend, FALSE)            AS is_weekend,
    COALESCE(h.is_non_business_day, FALSE)   AS is_non_business_day,
    (h.date_day IS NULL)                     AS holiday_calendar_missing
FROM intermediate.int_daily_complaint_volume v
LEFT JOIN staging.stg_weather_daily w
       ON w.date_day = v.date_day
      AND w.borough  = UPPER(TRIM(v.borough))
LEFT JOIN (
    SELECT date_day,
           AVG(temp_max_f)   AS temp_max_f,
           AVG(temp_min_f)   AS temp_min_f,
           AVG(temp_mean_f)  AS temp_mean_f,
           AVG(precip_in)    AS precip_in,
           AVG(snowfall_in)  AS snowfall_in,
           AVG(wind_max_mph) AS wind_max_mph
    FROM staging.stg_weather_daily
    GROUP BY 1
) cw ON cw.date_day = v.date_day
LEFT JOIN staging.stg_holidays_daily h
       ON h.date_day = v.date_day;

CREATE INDEX IF NOT EXISTS ix_int_enriched_day
    ON intermediate.int_daily_volume_enriched (date_day, borough);
