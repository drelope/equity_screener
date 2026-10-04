-- =====================================================================
-- V0006 dividend_amount_units
-- raw.dividend_data.amount was documented as a per-share amount, but the
-- SEC extractor ingested six us-gaap concepts into the same column with no
-- column recording which concept produced the row:
--
--   per-share : CommonStockDividendsPerShareDeclared
--   aggregate : CommonStockDividendsPaid, PreferredStockDividendsPaid,
--               DividendsCashPaid, DividendsCommonStockCash,
--               StockIssuedDuringPeriodValueCommonStockDividends
--
-- The aggregate concepts are total dollars for the period, so a 365-day
-- SUM mixed billions of dollars with per-share amounts and made
-- dividend_yield meaningless for every security with SEC coverage
-- (e.g. BAC-PL: 72.50 of payments alongside 20,153,000,000 of XBRL
-- "dividends"). The concept is now recorded so the unit is knowable and
-- the feature query can prefer one unit and one provider.
--
-- Existing SEC_XBRL rows are purged: their concept was never recorded, so
-- they cannot be told apart from the per-share ones and must be re-derived
-- by scripts/populate_dividend_data.py --sources sec. OpenBB rows are
-- per-share by construction and are left untouched.
-- =====================================================================

DO $migration$
BEGIN

ALTER TABLE raw.dividend_data ADD COLUMN IF NOT EXISTS concept VARCHAR(96);

COMMENT ON COLUMN raw.dividend_data.concept IS
  'Source XBRL concept (provider=SEC_XBRL) or empty; identifies whether amount '
  'is per-share or an aggregate dollar total, which raw.dividend_data.amount '
  'alone cannot express';

CREATE INDEX IF NOT EXISTS idx_dividend_data_provider_concept
  ON raw.dividend_data(provider, concept);

DELETE FROM raw.dividend_data WHERE provider = 'SEC_XBRL';

END
$migration$;
