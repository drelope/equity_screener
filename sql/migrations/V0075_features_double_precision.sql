-- =====================================================================
-- V0075: store model.features numeric metrics as double precision.
--
-- model.features is the widest relation in the database: 9.7M rows at ~270
-- bytes each (2.62 GB of live tuples). Almost the whole row is the ~35
-- populated NUMERIC metrics, each measured at ~11-12 bytes on disk because
-- NUMERIC stores the actual digits of the value and every row's value has
-- its own width. A double precision value is a fixed 8 bytes.
--
-- These columns are derived analytics, not a source of record. raw.market_data
-- and fundamentals.periodic_financials keep NUMERIC precisely because they are
-- the inputs a return or a yield is reconstructed from; model.features holds
-- ratios, margins and yields computed from them in float arithmetic (numpy /
-- pandas), so they are already float values which NUMERIC only re-encodes as
-- decimal text. double precision round-trips those floats exactly, where the
-- NUMERIC path goes float -> str -> Decimal and back.
--
-- Precision is sufficient: float8 carries ~15-16 significant digits. The
-- largest genuine magnitude in the table is a share price near $809,000
-- (BRK-A), which needs 11 digits to hold cents, and the smallest is a yield
-- near 1e-06, well inside the exponent range. Nothing here is money that gets
-- summed into a ledger; it is per-row features fed to a model.
--
-- Measured effect: the ALTER rewrites the table once and shrinks the live
-- tuple store from ~2.62 GB to ~1.6 GB.
--
-- The three RETIRED columns (liquidation_discount, legal_rights_score,
-- data_quality_score) are NULL on every row and are converted for consistency;
-- they cost nothing either way. target_sustainable_dividend is an integer label
-- and is untouched.
--
-- eps_ttm_growth and debt are added by V0014/V0021 as NUMERIC; the same clauses
-- are declared as double precision in sql/schema.sql, so a fresh build (which
-- runs those migrations before this one) converges on the same types.
-- =====================================================================

ALTER TABLE model.features
  ALTER COLUMN annualized_dividend TYPE double precision USING annualized_dividend::double precision,
  ALTER COLUMN capex_intensity TYPE double precision USING capex_intensity::double precision,
  ALTER COLUMN cash_conversion TYPE double precision USING cash_conversion::double precision,
  ALTER COLUMN current_price TYPE double precision USING current_price::double precision,
  ALTER COLUMN current_ratio TYPE double precision USING current_ratio::double precision,
  ALTER COLUMN data_quality_score TYPE double precision USING data_quality_score::double precision,
  ALTER COLUMN debt TYPE double precision USING debt::double precision,
  ALTER COLUMN debt_to_ebitda TYPE double precision USING debt_to_ebitda::double precision,
  ALTER COLUMN debt_to_equity TYPE double precision USING debt_to_equity::double precision,
  ALTER COLUMN dividend_coverage TYPE double precision USING dividend_coverage::double precision,
  ALTER COLUMN dividend_growth TYPE double precision USING dividend_growth::double precision,
  ALTER COLUMN dividend_yield TYPE double precision USING dividend_yield::double precision,
  ALTER COLUMN earnings_payout TYPE double precision USING earnings_payout::double precision,
  ALTER COLUMN earnings_yield TYPE double precision USING earnings_yield::double precision,
  ALTER COLUMN eps_ttm_growth TYPE double precision USING eps_ttm_growth::double precision,
  ALTER COLUMN fcf_growth TYPE double precision USING fcf_growth::double precision,
  ALTER COLUMN fcf_margin TYPE double precision USING fcf_margin::double precision,
  ALTER COLUMN fcf_payout TYPE double precision USING fcf_payout::double precision,
  ALTER COLUMN fcf_yield TYPE double precision USING fcf_yield::double precision,
  ALTER COLUMN gross_margin TYPE double precision USING gross_margin::double precision,
  ALTER COLUMN interest_coverage TYPE double precision USING interest_coverage::double precision,
  ALTER COLUMN legal_rights_score TYPE double precision USING legal_rights_score::double precision,
  ALTER COLUMN liquidation_discount TYPE double precision USING liquidation_discount::double precision,
  ALTER COLUMN momentum_252d TYPE double precision USING momentum_252d::double precision,
  ALTER COLUMN momentum_63d TYPE double precision USING momentum_63d::double precision,
  ALTER COLUMN net_debt TYPE double precision USING net_debt::double precision,
  ALTER COLUMN net_debt_to_ebitda TYPE double precision USING net_debt_to_ebitda::double precision,
  ALTER COLUMN net_margin TYPE double precision USING net_margin::double precision,
  ALTER COLUMN ocf_margin TYPE double precision USING ocf_margin::double precision,
  ALTER COLUMN operating_margin TYPE double precision USING operating_margin::double precision,
  ALTER COLUMN pe_ratio TYPE double precision USING pe_ratio::double precision,
  ALTER COLUMN price_to_book TYPE double precision USING price_to_book::double precision,
  ALTER COLUMN quick_liquidity TYPE double precision USING quick_liquidity::double precision,
  ALTER COLUMN raw_annual_dividend TYPE double precision USING raw_annual_dividend::double precision,
  ALTER COLUMN raw_current_price TYPE double precision USING raw_current_price::double precision,
  ALTER COLUMN raw_dividend_yield TYPE double precision USING raw_dividend_yield::double precision,
  ALTER COLUMN refinancing_wall TYPE double precision USING refinancing_wall::double precision,
  ALTER COLUMN volatility_252d TYPE double precision USING volatility_252d::double precision;
