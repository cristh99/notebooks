-- MotherDuck Operations Control Plane v1
--
-- Purpose:
--   Create a compact, live, read-only semantic layer for operational Dives,
--   agent queries, and human inspection without adding a polling Flight.
--
-- Authority boundary:
--   This migration creates only a schema and views in md:my_db.
--   It does not alter Flights, schedules, run history, external jobs, or source data.
--
-- Application requires an explicit schema-write authorization.

BEGIN TRANSACTION;

CREATE SCHEMA IF NOT EXISTS my_db.ops_control;

CREATE OR REPLACE VIEW my_db.ops_control.flight_inventory_current AS
SELECT
  flight_id::VARCHAR AS flight_id,
  flight_name,
  status,
  schedule_status,
  schedule_cron,
  schedule_status = 'SCHEDULE_STATUS_ACTIVE' AS schedule_active,
  schedule_cron IS NOT NULL AS schedule_declared,
  current_version,
  created_at,
  updated_at,
  date_diff('minute', updated_at, current_timestamp) AS minutes_since_update,
  updated_at >= current_timestamp - INTERVAL '6 hours' AS recently_updated,
  CASE
    WHEN lower(flight_name) LIKE '%ocr%' THEN 'OCR'
    WHEN lower(flight_name) LIKE '%acquisition%'
      OR lower(flight_name) LIKE '%ledger%'
      OR lower(flight_name) LIKE '%checkpoint%'
      THEN 'Adquisición / ledger'
    WHEN lower(flight_name) LIKE '%cost%'
      OR lower(flight_name) LIKE '%budget%'
      THEN 'Costos'
    WHEN lower(flight_name) LIKE '%legal%'
      OR lower(flight_name) LIKE '%evidence%'
      THEN 'Evidencia / legal'
    ELSE 'Otros'
  END AS function_group
FROM MD_LIST_FLIGHTS(
  "offset" => 0::UINTEGER,
  "limit" => 50000::UINTEGER
);

CREATE OR REPLACE VIEW my_db.ops_control.schedule_function_summary_current AS
SELECT
  function_group,
  COUNT(*) AS flights,
  COUNT(*) FILTER (WHERE schedule_active) AS active_schedules,
  COUNT(*) FILTER (
    WHERE schedule_active AND recently_updated
  ) AS recently_updated_active_schedules,
  MAX(updated_at) AS latest_update_utc
FROM my_db.ops_control.flight_inventory_current
GROUP BY function_group;

CREATE OR REPLACE VIEW my_db.ops_control.query_health_24h AS
WITH q AS (
  SELECT
    epoch(execution_time) AS execution_seconds,
    error_message,
    bytes_uploaded,
    bytes_downloaded,
    bytes_spilled_to_disk,
    start_time
  FROM md_information_schema.query_history
  WHERE start_time >= current_timestamp - INTERVAL '24 hours'
)
SELECT
  COUNT(*) AS queries,
  COUNT(*) FILTER (WHERE error_message IS NOT NULL) AS failed_queries,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE error_message IS NOT NULL)
      / NULLIF(COUNT(*), 0),
    2
  ) AS failure_rate_pct,
  ROUND(SUM(execution_seconds), 2) AS execution_seconds,
  SUM(bytes_uploaded) AS bytes_uploaded,
  SUM(bytes_downloaded) AS bytes_downloaded,
  SUM(bytes_spilled_to_disk) AS bytes_spilled_to_disk,
  MIN(start_time) AS window_start_utc,
  MAX(start_time) AS window_end_utc
FROM q;

CREATE OR REPLACE VIEW my_db.ops_control.query_activity_hourly_24h AS
WITH hours AS (
  SELECT hour_start
  FROM generate_series(
    date_trunc('hour', current_timestamp - INTERVAL '23 hours'),
    date_trunc('hour', current_timestamp),
    INTERVAL '1 hour'
  ) AS t(hour_start)
), activity AS (
  SELECT
    date_trunc('hour', start_time) AS hour_start,
    COUNT(*) AS queries,
    COUNT(*) FILTER (WHERE error_message IS NOT NULL) AS failed_queries,
    ROUND(SUM(epoch(execution_time)), 2) AS execution_seconds
  FROM md_information_schema.query_history
  WHERE start_time >= current_timestamp - INTERVAL '24 hours'
  GROUP BY hour_start
)
SELECT
  h.hour_start,
  strftime(h.hour_start, '%Y-%m-%d %H:00') AS hour_utc,
  COALESCE(a.queries, 0) AS queries,
  COALESCE(a.failed_queries, 0) AS failed_queries,
  COALESCE(a.execution_seconds, 0) AS execution_seconds
FROM hours h
LEFT JOIN activity a USING (hour_start)
ORDER BY h.hour_start;

CREATE OR REPLACE VIEW my_db.ops_control.recent_schedule_changes_current AS
SELECT
  flight_id,
  flight_name,
  function_group,
  schedule_cron,
  schedule_status,
  current_version,
  updated_at,
  minutes_since_update,
  recently_updated
FROM my_db.ops_control.flight_inventory_current
WHERE schedule_active
ORDER BY updated_at DESC, flight_name
LIMIT 50;

COMMIT;

-- Post-apply verification:
--
-- SELECT * FROM my_db.ops_control.query_health_24h;
-- SELECT * FROM my_db.ops_control.schedule_function_summary_current
-- ORDER BY active_schedules DESC, function_group;
-- SELECT COUNT(*) FROM my_db.ops_control.query_activity_hourly_24h;
-- SELECT * FROM my_db.ops_control.recent_schedule_changes_current LIMIT 10;
