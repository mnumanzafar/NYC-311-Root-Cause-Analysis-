-- staging: dense date spine so zero-volume days are not silently dropped.
-- Also carries the investigation windows used by the Power BI contribution measures.
CREATE SCHEMA IF NOT EXISTS staging;
DROP TABLE IF EXISTS staging.stg_calendar;

CREATE TABLE staging.stg_calendar AS
WITH bounds AS (
    SELECT MIN(created_date) AS d0, MAX(created_date) AS d1
    FROM staging.stg_311_requests
),
-- EDIT THESE to match the anomaly under investigation (mirrors config/config.yaml).
windows AS (
    SELECT
        DATE '2023-07-01' AS event_start,   -- suspected anomaly window
        DATE '2023-07-31' AS event_end,
        DATE '2023-06-01' AS baseline_start,-- comparable pre-period
        DATE '2023-06-30' AS baseline_end
)
SELECT
    d::date                                   AS date_day,
    EXTRACT(YEAR  FROM d)::int                AS year,
    EXTRACT(QUARTER FROM d)::int              AS quarter,
    EXTRACT(MONTH FROM d)::int                AS month,
    EXTRACT(DOY   FROM d)::int                AS day_of_year,
    TO_CHAR(d, 'Dy')                          AS day_name,
    EXTRACT(ISODOW FROM d) IN (6, 7)          AS is_weekend,
    (d::date BETWEEN w.event_start AND w.event_end)       AS in_event_window,
    (d::date BETWEEN w.baseline_start AND w.baseline_end) AS in_baseline_window
FROM bounds, windows w, GENERATE_SERIES(bounds.d0, bounds.d1, INTERVAL '1 day') AS d;
