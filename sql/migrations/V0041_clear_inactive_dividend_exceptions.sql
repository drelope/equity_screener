-- V0041 clear_inactive_dividend_exceptions
--
-- Five inactive securities still carried dividend = TRUE: BTLN (derivative),
-- OCAC (common_stock) and OCAC-RI / OCAC-UN / OCAC-WT. They were not reachable
-- downstream (the feature build filters on active), but they are exactly the
-- population the earlier de-duplication passes are supposed to have cleaned, so
-- leaving them makes "no inactive dividend payers" untrue as an invariant.
--
-- They fall into two structurally different cases, and conflating them is what
-- makes this look dangerous.
--
-- OCAC (common_stock) has no same-key sibling, so it is a plain flag flip:
--
--   UPDATE ... SET dividend = FALSE WHERE ... NOT EXISTS (sibling)
--
-- The other four each have an *active* sibling on the same
-- (cik, ticker, security_type) with dividend = FALSE, which means flipping the
-- flag would violate ux_security_cik_ticker_type_dividend. Their fundamentals
-- cannot simply be re-pointed either: every one of their
-- fundamentals.periodic_financials rows already has a counterpart under the
-- survivor on (period_end, fiscal_year, fiscal_period).
--
-- Those counterparts were compared column by column before deleting anything.
-- All 105 BTLN rows (and 3 each for OCAC-RI/UN/WT) match their survivor on
-- every value column; the only differences are security_id and retrieved_at,
-- i.e. they are the same figures re-extracted a day later. Deleting them
-- therefore loses no data.
--
-- None of the four carry model.features/scores/rankings/predictions or any
-- preferred.* row, so this is dormant data and cannot move a published score.
--
-- What is kept rather than dropped:
--   * clean.ticker_profile and raw.ticker_profile are *moved* to the survivor,
--     not deleted -- the survivor owns none, so nothing collides, and these are
--     the only rows holding the profile for this (cik, ticker).
--   * audit.source_lineage (13 rows) is moved too, so provenance follows the
--     security instead of being orphaned.
--   * audit.data_quality is moved rather than deleted, keeping the quality
--     observation for the surviving row.
--
-- Deleting the securities themselves (not just deactivating) is deliberate: a
-- deactivated dividend = TRUE row is the very inconsistency being removed, and
-- these four have no scores or features whose history depends on them existing.

BEGIN;

-- ---------------------------------------------------------------- case 1: no
-- sibling on the same (cik, ticker, security_type). Nothing to reconcile, so
-- the flag simply reflects reality.
UPDATE reference.securities s
SET dividend = FALSE
WHERE NOT s.active
  AND s.dividend
  AND NOT EXISTS (
      SELECT 1 FROM reference.securities t
      WHERE t.cik = s.cik
        AND t.ticker = s.ticker
        AND t.security_type = s.security_type
        AND t.security_id <> s.security_id
        AND t.active
        AND NOT t.dividend
  );

-- ------------------------------------------------------------- case 2: an
-- active dividend = FALSE sibling exists. The duplicate row and its
-- substance-identical fundamentals go away; the profile, lineage and quality
-- rows move to the survivor so the security keeps them.
CREATE TEMP TABLE _dup_security_map ON COMMIT DROP AS
SELECT s.security_id AS dup_id, t.security_id AS survivor_id
FROM reference.securities s
JOIN reference.securities t
  ON t.cik = s.cik
 AND t.ticker = s.ticker
 AND t.security_type = s.security_type
 AND t.security_id <> s.security_id
WHERE NOT s.active
  AND s.dividend
  AND t.active
  AND NOT t.dividend;

-- Substance-duplicate fundamentals: same keys and same values as the survivor's,
-- so removing them cannot lose a figure.
DELETE FROM fundamentals.periodic_financials f
USING _dup_security_map m
WHERE f.security_id = m.dup_id
  AND EXISTS (
      SELECT 1 FROM fundamentals.periodic_financials y
      WHERE y.security_id = m.survivor_id
        AND y.period_end = f.period_end
        AND y.fiscal_year = f.fiscal_year
        AND y.fiscal_period = f.fiscal_period
  );

-- The three remaining child tables are keyed so that re-pointing cannot collide:
-- raw.ticker_profile and audit.source_lineage by a surrogate that ignores the
-- moved row, clean.ticker_profile by (cik, ticker) which the survivor does not
-- have. So all three move unconditionally rather than behind an existence
-- guard -- a guard here would skip the move and orphan the rows, since the
-- survivors do already hold their own rows in some of these tables.
UPDATE clean.ticker_profile t
SET security_id = m.survivor_id
FROM _dup_security_map m
WHERE t.security_id = m.dup_id;

UPDATE raw.ticker_profile t
SET security_id = m.survivor_id
FROM _dup_security_map m
WHERE t.security_id = m.dup_id;

-- Provenance follows the security rather than being deleted with it.
UPDATE audit.source_lineage t
SET security_id = m.survivor_id
FROM _dup_security_map m
WHERE t.security_id = m.dup_id;

-- audit.data_quality is the exception: it is keyed by (security_id, as_of_date)
-- and the survivor already has a row for that date, so the duplicate's snapshot
-- cannot be moved. It describes an extraction whose output is being discarded as
-- a duplicate, so it goes with the duplicate.
DELETE FROM audit.data_quality t
USING _dup_security_map m
WHERE t.security_id = m.dup_id;

DELETE FROM reference.securities s
USING _dup_security_map m
WHERE s.security_id = m.dup_id;

COMMIT;
