-- V0089 fmp_fundamentals
--
-- FMP fundamental data (financial statements, discounted-cash-flow estimate and
-- company filings), gathered by scripts.populate_fmp_fundamentals from OpenBB's
-- FMP provider. Normalized key columns plus the provider's own line items in a
-- JSONB payload, the same raw-payload pattern as raw.companyfacts: FMP's field
-- set is broad and versioned, so the columns a consumer reads are extracted from
-- `metrics` rather than frozen into the table.
--
-- These rows are SUPPORTING data for the investment-analysis worksheet, not an
-- input to the model: fundamentals.periodic_financials stays SEC XBRL only, and
-- the feature build never reads these tables.

CREATE TABLE IF NOT EXISTS raw.fmp_statements (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  statement VARCHAR(16) NOT NULL,
  period_end DATE NOT NULL,
  fiscal_period VARCHAR(16) NOT NULL DEFAULT '',
  fiscal_year INT,
  filing_date DATE NOT NULL,
  reported_currency VARCHAR(8),
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash VARCHAR(64) NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'FMP',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, statement, period_end, fiscal_period, filing_date)
);

CREATE INDEX IF NOT EXISTS ix_fmp_statements_security_statement
  ON raw.fmp_statements (security_id, statement, period_end DESC);

COMMENT ON TABLE raw.fmp_statements IS
  'FMP income/balance/cash statements, one row per fiscal period per security. '
  'Supporting data for the analysis worksheet; not read by the model feature build.';
COMMENT ON COLUMN raw.fmp_statements.statement IS
  'FMP statement type: income | balance | cash';
COMMENT ON COLUMN raw.fmp_statements.metrics IS
  'The FMP statement row as JSONB (revenue, net_income, total_assets, free_cash_flow, '
  '...). The identity columns are also present in the payload; consumers read the keys '
  'they need.';
COMMENT ON COLUMN raw.fmp_statements.filing_date IS
  'The date FMP accepted the filing the figures came from. Part of the key so a '
  're-fetched period with a new acceptance date is a distinct observation.';

CREATE TABLE IF NOT EXISTS raw.fmp_dcf (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL,
  dcf NUMERIC,
  stock_price NUMERIC,
  reported_currency VARCHAR(8),
  provider VARCHAR(64) NOT NULL DEFAULT 'FMP',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, as_of_date)
);

COMMENT ON TABLE raw.fmp_dcf IS
  'FMP discounted-cash-flow estimate per security, read from FMP directly because '
  'OpenBB 4.7.2 exposes no DCF command in any provider. dcf is FMP''s intrinsic '
  'value per share and stock_price its then-current quote, so the margin of safety '
  'is dcf / stock_price - 1. Supporting data; not read by the model feature build.';
COMMENT ON COLUMN raw.fmp_dcf.as_of_date IS
  'The date FMP computed the estimate (FMP "date"), part of the key so successive '
  'estimates are retained as vintages.';

CREATE TABLE IF NOT EXISTS raw.fmp_filings (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  filing_date DATE NOT NULL,
  report_type VARCHAR(64) NOT NULL,
  report_url TEXT NOT NULL,
  filing_url TEXT,
  accepted_date TIMESTAMPTZ,
  provider VARCHAR(64) NOT NULL DEFAULT 'FMP',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, filing_date, report_type, report_url)
);

COMMENT ON TABLE raw.fmp_filings IS
  'FMP company filings, a second SEC-filings source alongside the direct SEC '
  'submissions in raw.sec_submissions. provider records which source answered; '
  'the two are kept separate so provenance is auditable.';
