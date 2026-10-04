-- =====================================================================
-- V0016 current_basis_liquidity
-- Separate the current-basis balance-sheet subtotals from the total-basis
-- columns they were sharing, so a quick ratio has a real denominator.
--
-- Why this migration exists
-- ------------------------
-- fundamentals.periodic_financials.liabilities was fed by two XBRL tags as
-- fallbacks for one slot:
--
--     "liabilities": ("Liabilities", "LiabilitiesCurrent")
--
-- Those are different quantities. Liabilities is the total balance-sheet
-- liability; LiabilitiesCurrent is the portion due within a year. A filer
-- reporting only the current subtotal was recorded as if it had reported the
-- total, and a quick ratio computed from that column would be wrong for
-- whichever basis lost -- overstating coverage for the total-basis filers and
-- understating it for the current-basis ones.
--
-- Measured against the stored data, the mixing was not subtle:
--
--   29,120 of 269,969 distinct rows had liabilities > assets
--   44,630 broke the assets = liabilities + equity identity
--   18,513 had a liabilities/assets ratio above 1.5
--
-- assets had the same defect with AssetsCurrent as a fallback for Assets.
--
-- Why add columns rather than repair liabilities in place
-- -------------------------------------------------------
-- The stored values are the only record of what each filer actually reported,
-- and which tag a row came from is not currently retained. Re-deriving the
-- column would mean re-fetching companyfacts for every issuer to learn whether
-- a given figure was the total or the current subtotal -- an unbounded ETL pass
-- against the SEC for a column nothing currently consumes. Adding the two
-- current-basis metrics alongside is bounded, additive, and lets the next
-- fundamentals rebuild populate them from facts already in hand.
--
-- liabilities and assets keep their existing values and meaning as the
-- total-basis figures. No consumer of either column exists today
-- (grep: the only readers are two tests in test_fundamentals_and_predictions.py,
-- which assert pass-through of a total-basis Assets value), so nothing is
-- invalidated by leaving them alone. What changes is that they stop accepting a
-- current-basis figure as a substitute going forward, which is where the wrong
-- numbers came from.
-- =====================================================================

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS current_assets NUMERIC,
  ADD COLUMN IF NOT EXISTS current_liabilities NUMERIC;

-- model.features.quick_liquidity, the materialised ratio.
--
-- This has to be here and not only in sql/schema.sql. V0001 is a baseline
-- marker rather than replayed DDL: migrate.py records the state that
-- schema.sql + init_db.py produced and never re-runs it, so schema.sql only
-- reaches a brand-new database. An established warehouse gets its columns from
-- migrations alone. The first cut of this work added the column to schema.sql
-- and nothing else, and the 07:00 nightly then died at stage 7 on
-- "column quick_liquidity does not exist" -- the same class of error V0011
-- documents for the leverage ratios, and the reason V0012 says outright that a
-- column on model.features must be added by migration or not at all.
ALTER TABLE model.features
  ADD COLUMN IF NOT EXISTS quick_liquidity NUMERIC;

COMMENT ON COLUMN model.features.quick_liquidity IS
  'Quick liquidity: cash and short-term investments over obligations due within '
  'a year (V0016). Both legs are current-basis, read from the same FY vintage '
  'on the point-in-time discipline the rest of the feature SQL uses. NULL when '
  'the denominator is absent or non-positive. Consumed by the credit variable '
  'strength score as a CVS leg; not a declared model.FEATURES input until '
  'V0012-style measurement shows the model uses it.';

COMMENT ON COLUMN fundamentals.periodic_financials.current_assets IS
  'AssetsCurrent: assets expected to be realised or consumed within a year. '
  'Stored separately from `assets` because it is a different quantity, not a '
  'fallback for it. Feeds quick_liquidity.';
COMMENT ON COLUMN fundamentals.periodic_financials.current_liabilities IS
  'LiabilitiesCurrent: obligations due within a year. The denominator of '
  'quick_liquidity, and the reason V0016 exists -- it was previously folded '
  'into `liabilities` as an XBRL fallback, mixing two accounting bases in one '
  'column. NULL for every row until the next fundamentals rebuild.';

-- No backfill. Every value here would have to come from raw.companyfacts, and
-- the honest statement is that this column is empty until the ETL runs. A
-- backfilled column cannot be distinguished from a measured one, and the whole
-- point of the split is that a reader can tell which is which.
