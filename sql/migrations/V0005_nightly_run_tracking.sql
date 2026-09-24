-- =====================================================================
-- V0005 nightly_run_tracking
-- Single-owner verification trail for the nightly ETL run and the module
-- audit performed by scripts/verify_nightly_run.py:
--
--   audit.nightly_runs   one row per ETL pipeline execution (who/trigger,
--                        start/finish, per-stage result, exit code).
--   audit.nightly_checks one row per verification pass (the dated,
--                        auditable "I checked" record).
--
-- Guarded/IF NOT EXISTS so the migration is idempotent and fresh installs
-- that already carry the tables (schema.sql) are skipped. Applied by
-- scripts/migrate.py as a single DO block.
-- =====================================================================

DO $migration$
BEGIN

CREATE TABLE IF NOT EXISTS audit.nightly_runs (
  run_id BIGSERIAL PRIMARY KEY,
  run_date DATE NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'manual',   -- manual | airflow | systemd
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  exit_code INT,
  stages JSONB NOT NULL DEFAULT '{}',       -- {module: ok|failed|skipped}
  status TEXT NOT NULL DEFAULT 'running',   -- running | success | failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS nightly_runs_run_date_idx
  ON audit.nightly_runs (run_date, started_at DESC);

CREATE TABLE IF NOT EXISTS audit.nightly_checks (
  check_id BIGSERIAL PRIMARY KEY,
  verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_date DATE NOT NULL,
  verified_by TEXT NOT NULL DEFAULT 'single-owner',
  status TEXT NOT NULL,                     -- ok | attention
  findings JSONB NOT NULL DEFAULT '{}',
  notes TEXT
);

CREATE INDEX IF NOT EXISTS nightly_checks_run_date_idx
  ON audit.nightly_checks (run_date, verified_at DESC);

END $migration$;