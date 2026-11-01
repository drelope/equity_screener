-- V0102: A per-source freshness series.
--
-- audit.nightly_checks stores each verification as one findings JSON document, so
-- "how old was raw.market_data on each of the last 60 nights" meant parsing JSON.
-- This table holds one row per (measurement, source), so a stale or slowly
-- degrading source is a plain query, and a source that stopped being measured shows
-- as a gap.
--
-- age_hours is NULL when the source held no rows at the time (it was not aged, so
-- within_sla is NULL as well: absence of data is not a breach).
BEGIN;

CREATE TABLE IF NOT EXISTS audit.source_freshness (
  measured_at TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL,
  age_hours NUMERIC,
  sla_hours NUMERIC NOT NULL,
  within_sla BOOLEAN,
  run_date DATE NOT NULL,
  PRIMARY KEY (source, measured_at)
);

CREATE INDEX IF NOT EXISTS source_freshness_run_date_idx
  ON audit.source_freshness (run_date);

COMMENT ON TABLE audit.source_freshness IS
  'One row per source per nightly verification: its age and the SLA it was held to';

CREATE OR REPLACE VIEW audit.source_freshness_latest AS
SELECT DISTINCT ON (source) source, measured_at, age_hours, sla_hours, within_sla, run_date
FROM audit.source_freshness
ORDER BY source, measured_at DESC;

COMMENT ON VIEW audit.source_freshness_latest IS
  'The most recent freshness measurement for each source';

COMMIT;
