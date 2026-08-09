-- mart: baseline vs. anomaly-window volumes per cohort, with change contribution.
-- Edit the window dates to match config/config.yaml analysis.anomaly_window.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_cohort_breakdown;

CREATE TABLE marts.mart_cohort_breakdown AS
WITH params AS (
    SELECT DATE '2023-07-01' AS anom_start, DATE '2023-09-30' AS anom_end
),
tagged AS (
    SELECT d.*,
           CASE
             WHEN d.date_day BETWEEN p.anom_start AND p.anom_end THEN 'anomaly'
             WHEN d.date_day BETWEEN p.anom_start - INTERVAL '1 year'
                                 AND p.anom_end   - INTERVAL '1 year' THEN 'baseline'
           END AS period
    FROM intermediate.int_daily_complaint_volume d, params p
),
agg AS (
    SELECT borough, complaint_type, channel,
           SUM(volume) FILTER (WHERE period = 'baseline') AS baseline_volume,
           SUM(volume) FILTER (WHERE period = 'anomaly')  AS anomaly_volume
    FROM tagged
    WHERE period IS NOT NULL
    GROUP BY 1, 2, 3
)
SELECT
    borough, complaint_type, channel,
    COALESCE(baseline_volume, 0) AS baseline_volume,
    COALESCE(anomaly_volume, 0)  AS anomaly_volume,
    COALESCE(anomaly_volume, 0) - COALESCE(baseline_volume, 0) AS abs_change,
    ROUND(100.0 * (COALESCE(anomaly_volume, 0) - COALESCE(baseline_volume, 0))
          / NULLIF(baseline_volume, 0), 2) AS pct_change,
    ROUND(100.0 * (COALESCE(anomaly_volume, 0) - COALESCE(baseline_volume, 0))
          / NULLIF(SUM(COALESCE(anomaly_volume, 0) - COALESCE(baseline_volume, 0)) OVER (), 0), 2)
          AS contribution_pct
FROM agg
ORDER BY abs_change;
