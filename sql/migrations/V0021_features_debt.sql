-- model.features.debt: the raw debt balance behind debt_to_ebitda and
-- interest_coverage.
--
-- The feature query has always selected `fy.debt_fy AS debt`; it simply was
-- not in FEATURE_COLUMNS, so the INSERT never carried it. Persisting it is
-- what lets circuit breakers C2 and C3 test their precondition -- whether a
-- filer reports any interest-bearing instruments at all. Without the balance
-- on the row, "no debt" and "debt never extracted" are the same NULL and the
-- precondition cannot be evaluated.
BEGIN;

ALTER TABLE model.features
  ADD COLUMN IF NOT EXISTS debt NUMERIC;

COMMENT ON COLUMN model.features.debt IS
  'Total reported interest-bearing debt at the FY vintage: noncurrent plus '
  'current plus finance leases, summed from whichever components the filer '
  'reported (fundamentals.extract_periodic_financials). Operating leases are '
  'excluded by design. NULL means the filer reported no debt concepts at all, '
  'which is the distinction C2/C3 preconditions on -- see V0020.';

INSERT INTO public.schema_migrations(version, name)
VALUES (21, 'features_debt')
ON CONFLICT (version) DO NOTHING;

COMMIT;