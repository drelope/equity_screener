-- V0094 historical_universe
--
-- The backtest universe is survivor-only: raw.company_ticker is the *current*
-- SEC snapshot, so a company that delisted before 2026 has no reference row,
-- no prices and no score. The backtest therefore never holds it, and its record
-- is measured on the companies that survived.
--
-- A historical security is one recovered from EDGAR filings after it left the
-- current snapshot. It is never part of the live universe (active stays FALSE),
-- so the nightly ETL, the dashboard book and the current-universe benchmark
-- ignore it. It is read only by the historical backfill stages, which opt in.
--
-- V0094 is forward-only. It adds the flag and the last trading date; the rows
-- are loaded separately, after review of the recovered ticker artifact.

ALTER TABLE reference.securities
    ADD COLUMN IF NOT EXISTS historical BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS delisted_date DATE;

CREATE INDEX IF NOT EXISTS ix_securities_historical
ON reference.securities (historical) WHERE historical;

COMMENT ON COLUMN reference.securities.historical IS
  'Recovered from EDGAR after leaving the current SEC snapshot (V0094); never active, '
  'only the opt-in historical backfill stages read it';
COMMENT ON COLUMN reference.securities.delisted_date IS
  'Last trading date recovered for a historical security; NULL until prices are loaded';
