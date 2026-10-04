-- =====================================================================
-- V0009 periodic_financials_filing_date
-- Make fundamentals availability knowable, not assumed.
--
-- fundamentals.periodic_financials stored no filing date, so the only way a
-- consumer could ask "was this figure public on date X?" was to compare
-- period_end to X. That is period-end alignment, and it is look-ahead:
--
--   * A quarter ending 2023-12-31 is not public on 2024-01-05. Median lag from
--     period_end to first filing is 224 days across a 300-payload sample, and
--     p90 is 523 days, so the error is routinely several months.
--
--   * Worse, a period is not one fact. The same period_end is reported in the
--     original filing and again as a comparative in every later filing, and may
--     be restated. 1,617 periods in that sample carry more than one distinct
--     filing date. The extractor kept only the most recently filed value, so
--     period-end alignment fed the model a restated figure years before it
--     existed, while a filed-date join against the latest vintage alone would
--     have hidden the original observation entirely.
--
-- So this migration adds the filing date and, with it, the notion of a vintage:
-- one row per (period, filing state) recording the content that was public at
-- that filing. A consumer resolves an as-of date by taking the latest vintage
-- whose filed <= as-of, which is correct for original and restated alike.
--
-- filed is NOT NULL and part of the primary key. A row without a filing date
-- cannot be placed in time, and the extractor now drops such facts at the
-- source, so every surviving row has provenance. The existing rows cannot be
-- backfilled -- their filing dates were never stored -- and leaving them in
-- place would be the worst outcome: they would either leak (if a consumer
-- treats NULL as "always available") or silently vanish (if the join requires
-- filed <= as_of). They are deleted here so the rebuild is total, and the count
-- is recorded so the deletion is auditable rather than silent.
--
-- Re-run:  python scripts/populate_fundamentals.py   (DB-only, no network)
-- =====================================================================

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS filed DATE;

DO $$
DECLARE
  orphan_rows BIGINT;
BEGIN
  SELECT count(*) INTO orphan_rows
  FROM fundamentals.periodic_financials
  WHERE filed IS NULL;

  IF orphan_rows > 0 THEN
    RAISE NOTICE 'V0009: deleting % rows with no filing date; their provenance was never stored and they cannot be placed in time. Rebuild with scripts/populate_fundamentals.py', orphan_rows;
  END IF;

  DELETE FROM fundamentals.periodic_financials WHERE filed IS NULL;
END $$;

ALTER TABLE fundamentals.periodic_financials
  ALTER COLUMN filed SET NOT NULL;

-- One row per (period, vintage): the same fiscal period may legitimately appear
-- more than once as later filings restate or repeat it.
ALTER TABLE fundamentals.periodic_financials
  DROP CONSTRAINT IF EXISTS periodic_financials_pkey;

ALTER TABLE fundamentals.periodic_financials
  ADD PRIMARY KEY (security_id, period_end, fiscal_period, filed);

-- The consumer-side predicate. Indexed because the feature build resolves, for
-- every (security, observation_date), the latest vintage of every period, which
-- is a range scan per security rather than a lookup.
CREATE INDEX IF NOT EXISTS periodic_financials_filed_idx
  ON fundamentals.periodic_financials (security_id, filed DESC, period_end DESC);

COMMENT ON COLUMN fundamentals.periodic_financials.filed IS
  'SEC filing date: the earliest date this row''s content was public. Rows are '
  'vintages, so a restated period appears more than once; resolve an as-of date '
  'by taking the latest row with filed <= as_of_date. NULL is not permitted -- a '
  'figure with no filing date has no knowable availability and is dropped at '
  'extraction rather than assumed to have been available.';
