-- mart: analysis-ready daily series with rolling baseline and YoY comparison.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_daily_volume_by_borough;

CREATE TABLE marts.mart_daily_volume_by_borough AS
WITH daily AS (
    SELECT date_day, borough, SUM(volume) AS volume
    FROM intermediate.int_daily_complaint_volume
    GROUP BY 1, 2
)
SELECT
    date_day,
    borough,
    volume,
    AVG(volume) OVER w28  AS rolling_mean_28d,
    STDDEV_SAMP(volume) OVER w28 AS rolling_std_28d,
    (volume - AVG(volume) OVER w28)
        / NULLIF(STDDEV_SAMP(volume) OVER w28, 0) AS rolling_z,
    LAG(volume, 364) OVER (PARTITION BY borough ORDER BY date_day) AS volume_ly,
    volume - LAG(volume, 364) OVER (PARTITION BY borough ORDER BY date_day) AS yoy_abs_change
FROM daily
WINDOW w28 AS (PARTITION BY borough ORDER BY date_day ROWS BETWEEN 27 PRECEDING AND CURRENT ROW);
