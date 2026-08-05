-- Rollback for MotherDuck Operations Control Plane v1
--
-- This removes only the views and schema created by
-- sql/motherduck-ops-control-plane.sql.

BEGIN TRANSACTION;

DROP VIEW IF EXISTS my_db.ops_control.recent_schedule_changes_current;
DROP VIEW IF EXISTS my_db.ops_control.query_activity_hourly_24h;
DROP VIEW IF EXISTS my_db.ops_control.query_health_24h;
DROP VIEW IF EXISTS my_db.ops_control.schedule_function_summary_current;
DROP VIEW IF EXISTS my_db.ops_control.flight_inventory_current;
DROP SCHEMA IF EXISTS my_db.ops_control;

COMMIT;
