-- mart: baseline vs. post-change cohort comparison, enriched with external drivers.
-- Grain: borough x complaint_type (one row per cohort pair), plus rollup rows so
-- Power BI can show "All boroughs" / "All categories" without breaking additivity
-- of the rate-based measures. Windows come from staging.stg_calendar.
CREATE SCHEMA IF NOT EXISTS marts;
DROP TABLE IF EXISTS marts.mart_cohort_comparison;

CREATE TABLE marts.mart_cohort_comparison AS
WITH agg AS (
    SELECT
        borough,
        complaint_type,
        COUNT(*) FILTER (WHERE cohort_period = 'Baseline')      AS baseline_days,
        COUNT(*) FILTER (WHERE cohort_period = 'Post-change')   AS post_days,
        SUM(volume) FILTER (WHERE cohort_period = 'Baseline')   AS baseline_volume,
        SUM(volume) FILTER (WHERE cohort_period = 'Post-change') AS post_volume,
        AVG(volume) FILTER (WHERE cohort_period = 'Baseline')   AS baseline_daily_avg,
        AVG(volume) FILTER (WHERE cohort_period = 'Post-change') AS post_daily_avg,
        STDDEV_SAMP(volume) FILTER (WHERE cohort_period = 'Baseline')    AS baseline_sigma,
        STDDEV_SAMP(volume) FILTER (WHERE cohort_period = 'Post-change') AS post_sigma,
        AVG(temp_max_f) FILTER (WHERE cohort_period = 'Baseline')    AS baseline_temp_max_f,
        AVG(temp_max_f) FILTER (WHERE cohort_period = 'Post-change') AS post_temp_max_f,
        AVG(precip_in) FILTER (WHERE cohort_period = 'Baseline')     AS baseline_precip_in,
        AVG(precip_in) FILTER (WHERE cohort_period = 'Post-change')  AS post_precip_in,
        SUM(CASE WHEN cohort_period = 'Baseline'    AND primary_driver <> 'Normal' THEN 1 ELSE 0 END)
            AS baseline_driver_days,
        SUM(CASE WHEN cohort_period = 'Post-change' AND primary_driver <> 'Normal' THEN 1 ELSE 0 END)
            AS post_driver_days,
        SUM(CASE WHEN cohort_period = 'Baseline'    AND is_non_business_day THEN 1 ELSE 0 END)
            AS baseline_non_business_days,
        SUM(CASE WHEN cohort_period = 'Post-change' AND is_non_business_day THEN 1 ELSE 0 END)
            AS post_non_business_days
    FROM marts.mart_cohort_daily
    GROUP BY 1, 2
),
scaled AS (
    SELECT
        a.*,
        -- length-normalised comparison: what the baseline total would have been
        -- had it covered the same number of days as the post-change window.
        COALESCE(a.baseline_daily_avg, 0) * COALESCE(a.post_days, 0) AS baseline_volume_scaled
    FROM agg a
)
SELECT
    borough,
    complaint_type,
    baseline_days,
    post_days,
    COALESCE(baseline_volume, 0) AS baseline_volume,
    COALESCE(post_volume, 0)     AS post_volume,
    baseline_daily_avg,
    post_daily_avg,
    baseline_sigma,
    post_sigma,
    baseline_volume_scaled,
    COALESCE(post_volume, 0) - baseline_volume_scaled AS abs_change,
    100.0 * (COALESCE(post_daily_avg, 0) - COALESCE(baseline_daily_avg, 0))
        / NULLIF(baseline_daily_avg, 0) AS pct_change,
    -- share of the citywide change carried by this cohort
    100.0 * (COALESCE(post_volume, 0) - baseline_volume_scaled)
        / NULLIF(SUM(COALESCE(post_volume, 0) - baseline_volume_scaled) OVER (), 0)
        AS contribution_pct,
    -- standardised effect size (Cohen's d, pooled sd) for ranking cohorts
    (COALESCE(post_daily_avg, 0) - COALESCE(baseline_daily_avg, 0))
        / NULLIF(SQRT((COALESCE(baseline_sigma, 0) * COALESCE(baseline_sigma, 0)
                     + COALESCE(post_sigma, 0) * COALESCE(post_sigma, 0)) / 2.0), 0)
        AS effect_size_d,
    baseline_temp_max_f,
    post_temp_max_f,
    post_temp_max_f - baseline_temp_max_f AS temp_max_f_delta,
    baseline_precip_in,
    post_precip_in,
    post_precip_in - baseline_precip_in AS precip_in_delta,
    baseline_driver_days,
    post_driver_days,
    100.0 * baseline_driver_days / NULLIF(baseline_days, 0) AS baseline_driver_day_pct,
    100.0 * post_driver_days / NULLIF(post_days, 0)         AS post_driver_day_pct,
    baseline_non_business_days,
    post_non_business_days,
    -- mix guard: flags cohorts whose comparison is confounded by calendar mix
    (ABS(100.0 * baseline_non_business_days / NULLIF(baseline_days, 0)
       - 100.0 * post_non_business_days / NULLIF(post_days, 0)) > 10)
        AS calendar_mix_warning
FROM scaled;

CREATE INDEX IF NOT EXISTS ix_mcc_bor_type
    ON marts.mart_cohort_comparison (borough, complaint_type);
