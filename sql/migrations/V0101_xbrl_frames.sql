-- V0101: Snapshot of SEC XBRL Frames for cross-sectional sanity checks.
--
-- A frame is one concept for every filer over one calendar period, in a single
-- SEC response. Storing it lets a peer median (all filers in a SIC group, one
-- concept, one period) be computed from the warehouse instead of by looping
-- per-company calls.
BEGIN;

CREATE TABLE IF NOT EXISTS raw.xbrl_frames (
  taxonomy VARCHAR(32) NOT NULL,
  concept VARCHAR(128) NOT NULL,
  unit VARCHAR(32) NOT NULL,
  period VARCHAR(16) NOT NULL,
  cik VARCHAR(20) NOT NULL,
  entity_name TEXT,
  value NUMERIC NOT NULL,
  period_end DATE,
  accession VARCHAR(32),
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (taxonomy, concept, unit, period, cik)
);

CREATE INDEX IF NOT EXISTS xbrl_frames_cik_idx ON raw.xbrl_frames (cik);

COMMENT ON TABLE raw.xbrl_frames IS
  'SEC Frames API snapshot: one value per filer per (concept, unit, calendar period)';
COMMENT ON COLUMN raw.xbrl_frames.period IS
  'Frames period code: CY2023 (annual duration), CY2023Q4 (quarter), CY2023Q4I (instant)';

COMMIT;
