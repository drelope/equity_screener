-- V0100: Macro series vintages (ALFRED) for point-in-time reads.
--
-- raw.macro_series keeps one value per (series, observation date) and upserts in
-- place, so a revision overwrites what was known at the time. A backtest reading
-- it sees revised numbers as if they had always been available. This table keeps
-- every vintage: the value of an observation as it stood from vintage_date on.
-- raw.macro_series is left as is; the memo, API and risk-free lookup read "latest".
BEGIN;

CREATE TABLE IF NOT EXISTS raw.macro_series_vintages (
  series_id VARCHAR(64) NOT NULL,
  observation_date DATE NOT NULL,
  vintage_date DATE NOT NULL,
  value NUMERIC NOT NULL,
  unit VARCHAR(32) NOT NULL,
  source VARCHAR(16) NOT NULL,
  provider VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, observation_date, vintage_date)
);

CREATE INDEX IF NOT EXISTS macro_series_vintages_asof_idx
  ON raw.macro_series_vintages (series_id, vintage_date);

COMMENT ON TABLE raw.macro_series_vintages IS
  'ALFRED real-time history: the value of each observation from vintage_date until the next vintage';
COMMENT ON COLUMN raw.macro_series_vintages.vintage_date IS
  'First date this value was published (ALFRED realtime_start)';

COMMIT;
