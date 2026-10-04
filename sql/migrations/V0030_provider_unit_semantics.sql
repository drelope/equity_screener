-- Store a corroborated canonical yield fraction without overwriting the
-- provider-native yield value. Other ratios remain provider-native until
-- their field-level units can be independently established.
ALTER TABLE clean.company_profile
  ADD COLUMN IF NOT EXISTS dividend_yield_fraction NUMERIC,
  ADD COLUMN IF NOT EXISTS dividend_yield_source_unit VARCHAR(32);

COMMENT ON COLUMN clean.company_profile.dividend_yield IS
  'Provider-native yield in percent points when supplied by OpenBB/YFinance; original value is preserved';
COMMENT ON COLUMN clean.company_profile.dividend_yield_fraction IS
  'Canonical decimal yield fraction, populated only when dividend_rate/current_price corroborates the source unit';
COMMENT ON COLUMN clean.company_profile.dividend_yield_source_unit IS
  'How source dividend_yield was interpreted: fraction, percent_points, ambiguous, or unverified';
COMMENT ON COLUMN clean.company_profile.payout_ratio IS
  'Provider-native payout ratio; no scaling is applied without source-unit confirmation';
COMMENT ON COLUMN clean.company_profile.debt_to_equity IS
  'Provider leverage multiple, not a percentage; raw provider value is preserved';
COMMENT ON COLUMN clean.company_profile.quick_ratio IS
  'Provider-native liquidity multiple, not a percentage';
COMMENT ON COLUMN clean.company_profile.current_ratio IS
  'Provider-native liquidity multiple, not a percentage';
COMMENT ON COLUMN clean.company_profile.gross_margins IS
  'Provider margin fraction where 0.25 represents 25 percent';
COMMENT ON COLUMN clean.company_profile.ebitda_margins IS
  'Provider margin fraction where 0.25 represents 25 percent';
COMMENT ON COLUMN clean.company_profile.profit_margins IS
  'Provider margin fraction where 0.25 represents 25 percent';
COMMENT ON COLUMN clean.company_profile.operating_margins IS
  'Provider margin fraction where 0.25 represents 25 percent';
COMMENT ON COLUMN clean.company_profile.revenue_growth IS
  'Provider growth fraction where 0.10 represents 10 percent';
COMMENT ON COLUMN clean.company_profile.return_on_assets IS
  'Provider return fraction where 0.05 represents 5 percent';
COMMENT ON COLUMN clean.company_profile.return_on_equity IS
  'Provider return fraction where 0.05 represents 5 percent';

COMMENT ON COLUMN clean.ticker_profile.classification_conflict IS
  'TRUE only when the highest-ranked classifier evidence ties across distinct security types; lower-ranked alternatives are retained in source_profiles';

-- Compatibility guard for installations where a different V0029 was
-- previously recorded under the same version number.
ALTER TABLE reference.securities
  ADD COLUMN IF NOT EXISTS dividend_last_paid DATE;
COMMENT ON COLUMN reference.securities.dividend IS
  'Whether SEC evidence indicates that the security pays a dividend. Requires a positive dividend fact whose period ends within the recency window before the classification date.';
COMMENT ON COLUMN reference.securities.dividend_last_paid IS
  'Period end of the most recent positive dividend fact that qualified the security as a current payer; NULL when not a current payer';