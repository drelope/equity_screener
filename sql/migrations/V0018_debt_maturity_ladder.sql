-- =====================================================================
-- V0018 debt_maturity_ladder
-- Give C4 the input the specification twice claimed did not exist.
--
-- The claim, and why it was wrong
-- -----------------------------
-- Section 4.1 and section 6.2 both record that C4 "needs a contractual debt
-- maturity schedule, which XBRL does not expose as a fact", and treat C4 as a
-- missing *source* rather than a missing value. Measured against the stored
-- companyfacts payloads:
--
--   2,748 of 7,079 companies  LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths
--   2,740 of 7,079 companies  LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo
--   2,680 of 7,079 companies  both
--
-- They are standard us-gaap tags, and they are instant facts at the fiscal
-- year end -- the same vintage as the balance sheet, so they need no separate
-- aggregation and no second extraction path. The specification was written
-- against an assumption about footnote data that turned out to be wrong, and
-- the assumption was load-bearing: it is what kept C4 permanently unsourced
-- and therefore permanently unavailable.
--
-- What is stored, and what is deliberately not
-- -------------------------------------------
-- Year three exists as a tag too (2,655 companies) and is NOT carried here. C4
-- is an 18-month test. Year three falls outside that window, and storing a
-- column nobody asked for is how a figure ends up feeding a decision it was
-- never reviewed for.
--
-- Undrawn facilities are also excluded, and this is the substantive
-- judgement call. Section 6.2 defines liquid reserves as "Cash + Committed
-- Undrawn Facilities". Only 888 of 7,079 companies report a remaining
-- borrowing capacity at all, and an undrawn revolver is a commitment rather
-- than a reserve: it can be withdrawn against, cancelled, or priced such that
-- drawing it triggers a covenant. Counting it as cash overstates liquidity
-- precisely for the companies most likely to need it. The ratio is therefore
-- cash-only, which is the conservative direction section 4.1's house standard
-- requires -- a disclosure gap must cost the filer, not pay it.
--
-- This narrows C4's denominator rather than widening it, so the ratio computed
-- downstream is an upper bound on distress, never a lower one.
-- =====================================================================

ALTER TABLE fundamentals.periodic_financials
  ADD COLUMN IF NOT EXISTS debt_maturing_12m NUMERIC,
  ADD COLUMN IF NOT EXISTS debt_maturing_year_2 NUMERIC;

COMMENT ON COLUMN fundamentals.periodic_financials.debt_maturing_12m IS
  'LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths: contractual '
  'principal due within a year, from the debt footnote. Instant fact at the '
  'fiscal year end. 2,748 of 7,079 stored companyfacts report it.';
COMMENT ON COLUMN fundamentals.periodic_financials.debt_maturing_year_2 IS
  'LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo: contractual principal '
  'due in months 13-24. Used with debt_maturing_12m to interpolate C4''s '
  '18-month window. 2,740 of 7,079 stored companyfacts report it. Year three '
  'is outside the C4 window and is deliberately not stored.';

ALTER TABLE model.features
  ADD COLUMN IF NOT EXISTS refinancing_wall NUMERIC;

COMMENT ON COLUMN model.features.refinancing_wall IS
  'Maturity cliff: contractual principal due within 18 months over cash. '
  '(debt_maturing_12m + 0.5 * debt_maturing_year_2) / cash, both legs from the '
  'same FY vintage. C4 breaches at 1.0 -- maturities exceeding reserves. '
  'Undrawn facilities are excluded from the denominator: only 888 of 7,079 '
  'filers report them and a commitment is not a reserve, so including them '
  'would understate the cliff. Values above ~0.25 carry real weight in the '
  'CVS bracket table.';