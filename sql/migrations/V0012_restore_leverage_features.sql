-- =====================================================================
-- V0012 restore_leverage_features
-- Re-document the two ratio features whose inputs V0011 supplies.
--
-- V0010 retired debt_to_ebitda and interest_coverage with the reasons "no
-- D&A/EBITDA in schema" and "no interest expense line in schema". Those were
-- accurate about the materialised columns and wrong about the underlying data:
-- raw.companyfacts retains the full XBRL payload, and V0011 populates the three
-- concepts the ratios need (61.7% of candidates resolve D&A, 64.0% interest
-- expense; see V0011 for the full measurement and for why the shares figure is
-- quoted us-gaap-only). The features are therefore restored in
-- src/crispdm/features.py and their column comments replaced here.
--
-- No schema change: both columns have existed on model.features since V0003 and
-- were simply never written. They were being written as NULL -- permanently,
-- because INSERT_FEATURE omitted them -- while the app displayed them, which is
-- why debt_to_ebitda showed as empty for every equity.
--
-- The other three retired features stay retired, and their comments are
-- restated here so this file is the single place a reader can check which
-- retirements still hold:
--   * liquidation_discount -- not a coverage problem. It needs a liquidation
--     preference, which is a preferred-stock concept; the universe is 57%
--     common_stock, for which the metric is undefined rather than unknown. No
--     data source resolves it. V0011 adds shares_outstanding, which makes
--     equity value derivable, but that is a precondition for a different
--     metric and does not by itself restore this one.
--   * legal_rights_score -- preferred.contract_terms holds 2 rows against
--     11,015 securities. Carries 25% of the composite weight, which scoring.py
--     neutralises with fillna(0.5); the weight itself is a separate policy
--     decision and is deliberately untouched here.
--   * data_quality_score -- audit.data_quality is a two-date snapshot, not a
--     per-as-of-date series, so joining it would either match nothing or leak
--     today's score into every historical row.
-- =====================================================================

COMMENT ON COLUMN model.features.debt_to_ebitda IS
  'Total debt divided by EBITDA, where EBITDA is operating_income + '
  'depreciation_amortization from fundamentals.periodic_financials on a '
  'trailing basis with the last full year as fallback. NULL when the ratio is '
  'not computable: no debt, no D&A, or a non-positive EBITDA denominator. A '
  'negative EBITDA company is not recorded as 0 leverage -- NULL says the '
  'denominator is not a number, and the earnings and coverage features carry '
  'the distress signal instead. Roughly a third of filers disclose no D&A '
  'line, and that sparsity is real coverage, not a gap to impute.';

COMMENT ON COLUMN model.features.interest_coverage IS
  'Operating income (EBIT) divided by interest expense, trailing basis with '
  'the last full year as fallback. NULL when the ratio is not computable, and '
  'in particular when interest expense is not disclosed: a filer that folds '
  'interest into another line is recorded as unknown, not as zero interest, '
  'which would otherwise read as unbounded coverage.';
