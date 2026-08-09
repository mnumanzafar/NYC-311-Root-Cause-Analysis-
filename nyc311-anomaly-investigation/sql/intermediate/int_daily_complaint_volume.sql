-- intermediate: deduplicated request grain -> dense daily grain per segment.
CREATE SCHEMA IF NOT EXISTS intermediate;
DROP TABLE IF EXISTS intermediate.int_daily_complaint_volume;

CREATE TABLE intermediate.int_daily_complaint_volume AS
WITH deduped AS (
    SELECT DISTINCT ON (request_id) *
    FROM staging.stg_311_requests
    ORDER BY request_id, created_at
),
grain AS (
    SELECT c.date_day, s.borough, s.complaint_type, s.channel
    FROM staging.stg_calendar c
    CROSS JOIN (SELECT DISTINCT borough, complaint_type, channel FROM deduped) s
),
agg AS (
    SELECT created_date AS date_day, borough, complaint_type, channel,
           COUNT(*) AS volume,
           AVG(resolution_hours) AS avg_resolution_hours,
           COUNT(*) FILTER (WHERE closed_at IS NOT NULL) AS closed_volume
    FROM deduped
    GROUP BY 1, 2, 3, 4
)
SELECT g.date_day, g.borough, g.complaint_type, g.channel,
       COALESCE(a.volume, 0) AS volume,
       a.avg_resolution_hours,
       COALESCE(a.closed_volume, 0) AS closed_volume
FROM grain g
LEFT JOIN agg a
  ON  a.date_day = g.date_day
  AND a.borough IS NOT DISTINCT FROM g.borough
  AND a.complaint_type = g.complaint_type
  AND a.channel = g.channel;

CREATE INDEX ON intermediate.int_daily_complaint_volume (date_day);
