-- staging: rename, type, and lightly clean raw.nyc311_requests. No business logic.
CREATE SCHEMA IF NOT EXISTS staging;
DROP TABLE IF EXISTS staging.stg_311_requests;

CREATE TABLE staging.stg_311_requests AS
SELECT
    unique_key::bigint                                   AS request_id,
    created_date::timestamp                              AS created_at,
    NULLIF(closed_date, '')::timestamp                   AS closed_at,
    (created_date::timestamp)::date                      AS created_date,
    UPPER(NULLIF(TRIM(borough), ''))                     AS borough,
    INITCAP(TRIM(complaint_type))                        AS complaint_type,
    INITCAP(TRIM(COALESCE(descriptor, 'Unspecified')))   AS descriptor,
    UPPER(TRIM(agency))                                  AS agency,
    LOWER(TRIM(COALESCE(open_data_channel_type, 'unknown'))) AS channel,
    NULLIF(TRIM(status), '')                             AS status,
    NULLIF(TRIM(incident_zip), '')                       AS zip_code,
    NULLIF(latitude, '')::numeric                        AS latitude,
    NULLIF(longitude, '')::numeric                       AS longitude,
    EXTRACT(EPOCH FROM (NULLIF(closed_date, '')::timestamp - created_date::timestamp))
        / 3600.0                                         AS resolution_hours
FROM raw.nyc311_requests
WHERE created_date IS NOT NULL
  AND unique_key IS NOT NULL
  AND (NULLIF(closed_date, '')::timestamp IS NULL
       OR NULLIF(closed_date, '')::timestamp >= created_date::timestamp);

CREATE INDEX ON staging.stg_311_requests (created_date);
CREATE INDEX ON staging.stg_311_requests (borough, complaint_type);
