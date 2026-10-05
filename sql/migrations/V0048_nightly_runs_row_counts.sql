-- V0048 nightly_runs_row_counts
--
-- audit.nightly_runs recorded only per-stage status, so there was no measured
-- baseline for how much the universe changes night to night. Churn tolerances
-- in MatcherNarrowingDiffTemplate.md were estimated from created_at instead.
-- row_counts stores a snapshot taken when the run finishes; churn is the
-- difference between consecutive runs.

ALTER TABLE audit.nightly_runs
  ADD COLUMN IF NOT EXISTS row_counts JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN audit.nightly_runs.row_counts IS
  'Row-count snapshot at run end (securities total/active/dividend payers, active duplicate (cik, ticker) pairs, features and predictions at the latest as_of_date, preferred terms). Diff consecutive runs for churn.';
