CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS clean;
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS fundamentals;
CREATE SCHEMA IF NOT EXISTS dividends;
CREATE SCHEMA IF NOT EXISTS preferred;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS model;
CREATE SCHEMA IF NOT EXISTS audit;

-- The compose stack preloads pg_stat_statements via shared_preload_libraries.
-- Preloading only makes the library available to CREATE EXTENSION; without this
-- the server carries the preload overhead and the pg_stat_statements view never
-- exists, so the setting does nothing. Idempotent, and a no-op on a server that
-- did not preload it (the extension is then unavailable and this raises, which
-- is the honest signal rather than a silent skip).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS raw.company_ticker (
  ticker VARCHAR(32) PRIMARY KEY,
  cik VARCHAR(10) NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT NOT NULL DEFAULT 'https://www.sec.gov/files/company_tickers.json',
  raw_payload JSONB NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_company_ticker_ticker_cik
ON raw.company_ticker(ticker, cik);

CREATE TABLE IF NOT EXISTS reference.issuers (
  issuer_id BIGSERIAL PRIMARY KEY, cik VARCHAR(20) UNIQUE,
  issuer_name TEXT NOT NULL, sic VARCHAR(10), fiscal_year_end VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS reference.exchanges (
  exchange_id SERIAL PRIMARY KEY, exchange_code VARCHAR(32) UNIQUE NOT NULL,
  exchange_name TEXT
);

CREATE TABLE IF NOT EXISTS reference.securities (
  ticker VARCHAR(32) NOT NULL,
  cik VARCHAR(10) NOT NULL,
  security_id UUID PRIMARY KEY,
  issuer_id BIGINT REFERENCES reference.issuers(issuer_id),
  security_name TEXT NOT NULL,
  security_type VARCHAR(32) NOT NULL DEFAULT 'other',
  coupon_rate NUMERIC,
  dividend BOOLEAN NOT NULL DEFAULT FALSE,
  dividend_last_paid DATE,
  sec_data_status VARCHAR(32) NOT NULL DEFAULT 'unavailable',
  cusip VARCHAR(32), isin VARCHAR(32),
  exchange_id INT REFERENCES reference.exchanges(exchange_id),
  currency VARCHAR(8) NOT NULL DEFAULT 'USD', liquidation_preference NUMERIC,
  call_date DATE, active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now(),
  -- Data-quality guards: CIKs are zero-padded digits, currency is an ISO code
  -- and security_type is drawn from the normalized vocabulary maintained in
  -- src.crispdm.xbrl_tags.SECURITY_FACT_RULES and classify_security_type().
  CONSTRAINT chk_securities_cik
    CHECK (cik ~ '^[0-9]{1,10}$'),
  CONSTRAINT chk_securities_security_type
    CHECK (security_type IN (
      'common_stock', 'preferred stock', 'debt', 'equity',
      'other_equity', 'other_debt', 'option', 'future', 'derivative',
      'government debt', 'corporate bond', 'other_debt_and_equity', 'other'
    )),
  CONSTRAINT chk_securities_currency
    CHECK (currency ~ '^[A-Z]{3}$')
);
CREATE INDEX IF NOT EXISTS ix_securities_issuer_id
  ON reference.securities (issuer_id);
CREATE INDEX IF NOT EXISTS ix_securities_exchange_id
  ON reference.securities (exchange_id);
CREATE INDEX IF NOT EXISTS ix_securities_ticker_cik
  ON reference.securities (ticker, cik);

-- Converge databases created before the XBRL-term columns existed so the
-- COMMENT statements below and the profile/taxonomy writers always apply.
ALTER TABLE reference.securities
  ADD COLUMN IF NOT EXISTS coupon_rate NUMERIC,
  ADD COLUMN IF NOT EXISTS liquidation_preference NUMERIC,
  ADD COLUMN IF NOT EXISTS call_date DATE,
  ADD COLUMN IF NOT EXISTS classify_source VARCHAR(32),
  ADD COLUMN IF NOT EXISTS classify_confidence VARCHAR(16),
  ADD COLUMN IF NOT EXISTS classification_evidence JSONB;

-- Per-instrument classifier audit columns (see
-- src.crispdm.sec_client.classify_instrument): classify_source names the
-- deciding signal (symbol_suffix / dei_title / submissions_leading /
-- dividend_facts / concept_bag / unavailable), classify_confidence rates it,
-- and classification_evidence is the ordered evidence trail plus conflicts.
ALTER TABLE reference.securities
  ADD COLUMN IF NOT EXISTS classify_source VARCHAR(32),
  ADD COLUMN IF NOT EXISTS classify_confidence VARCHAR(16),
  ADD COLUMN IF NOT EXISTS classification_evidence JSONB;

COMMENT ON COLUMN reference.securities.ticker IS
  'dei:TradingSymbol; listed ticker symbol, for example ACR, ACR-PC, or ACR-PD';
COMMENT ON COLUMN reference.securities.cik IS
  'SEC Central Index Key, normalized to a zero-padded 10-character value';
COMMENT ON COLUMN reference.securities.security_id IS
  'Stable identifier for one listed security series';
COMMENT ON COLUMN reference.securities.issuer_id IS
  'Foreign key to reference.issuers';
COMMENT ON COLUMN reference.securities.security_name IS
  'Per-class dei:SecurityTitle / dei:Security12bTitle exactly as reported on the '
  'Form 8-K or annual-report cover for THIS registered class, e.g. '
  '"7.875% Series D Cumulative Redeemable Preferred Stock" for ACR-PD; sourced from '
  'raw.sec_instrument_titles (one cover title per ticker), falling back to the '
  'bound dei cover title from the companyfacts payload';
COMMENT ON COLUMN reference.securities.security_type IS
  'Normalized security classification, such as common_stock or preferred stock';
COMMENT ON COLUMN reference.securities.cusip IS
  'us-gaap:CUSIP or us-gaap:DebtInstrumentCusip; security CUSIP';
COMMENT ON COLUMN reference.securities.isin IS
  'us-gaap:ISIN or srt:ISIN; security ISIN';
COMMENT ON COLUMN reference.securities.exchange_id IS
  'Foreign key to reference.exchanges';
COMMENT ON COLUMN reference.securities.coupon_rate IS
  'Annual coupon or stated dividend rate, expressed as a percentage';
COMMENT ON COLUMN reference.securities.dividend IS
  'Whether SEC evidence indicates that the security pays a dividend. '
  'When ENFORCE_DIVIDEND_RECENCY is enabled, requires a positive dividend '
  'fact whose period ends within the recency window (DIVIDEND_RECENCY_DAYS, '
  '548 days) before the classification date; off by default to preserve the '
  'historical any-positive-fact rule. XBRL retains stale comparative facts '
  'that would otherwise keep defunct issuers in the universe';
COMMENT ON COLUMN reference.securities.dividend_last_paid IS
  'Period end (end date) of the most recent positive dividend fact that '
  'qualified reference.securities.dividend, or NULL when not a current payer';
COMMENT ON COLUMN reference.securities.currency IS
  'Currency code for security amounts, normally USD';
COMMENT ON COLUMN reference.securities.liquidation_preference IS
  'Preferred security liquidation preference per share';
COMMENT ON COLUMN reference.securities.call_date IS
  'Date on which the issuer may call or redeem the security';
COMMENT ON COLUMN reference.securities.created_at IS
  'Timestamp when the canonical security row was created';
COMMENT ON COLUMN reference.securities.updated_at IS
  'Timestamp when the canonical security row was last updated';
COMMENT ON COLUMN reference.securities.sec_data_status IS
  'Availability status of SEC data for this security';
COMMENT ON COLUMN reference.securities.classify_source IS
  'Signal that decided security_type (symbol_suffix, dei_title, submissions_leading, dividend_facts, concept_bag, unavailable)';
COMMENT ON COLUMN reference.securities.classify_confidence IS
  'Confidence of the classify_source decision (high, medium, low)';
COMMENT ON COLUMN reference.securities.classification_evidence IS
  'Ordered evidence trail and conflicts recorded by classify_instrument';

CREATE TABLE IF NOT EXISTS raw.market_data (
  security_id UUID REFERENCES reference.securities(security_id),
  observation_date DATE NOT NULL,
  open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
  adjusted_close NUMERIC, volume BIGINT, provider VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(security_id, observation_date, provider)
);

CREATE TABLE IF NOT EXISTS raw.ticker_profile (
  security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
  ticker VARCHAR(32) NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'OPENBB_YFINANCE',
  sector TEXT,
  industry TEXT,
  security_type TEXT,
  coupon_type VARCHAR(32),
  coupon_rate NUMERIC,
  fixed_period_end DATE,
  floating_spread NUMERIC,
  tax_status VARCHAR(32),
  call_date DATE,
  liquidation_preference NUMERIC,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Converge databases created before the profile columns existed.
ALTER TABLE raw.ticker_profile
  ADD COLUMN IF NOT EXISTS sector TEXT,
  ADD COLUMN IF NOT EXISTS industry TEXT,
  ADD COLUMN IF NOT EXISTS security_type TEXT,
  ADD COLUMN IF NOT EXISTS coupon_type VARCHAR(32),
  ADD COLUMN IF NOT EXISTS coupon_rate NUMERIC,
  ADD COLUMN IF NOT EXISTS fixed_period_end DATE,
  ADD COLUMN IF NOT EXISTS floating_spread NUMERIC,
  ADD COLUMN IF NOT EXISTS tax_status VARCHAR(32),
  ADD COLUMN IF NOT EXISTS call_date DATE,
  ADD COLUMN IF NOT EXISTS liquidation_preference NUMERIC,
  ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN raw.ticker_profile.coupon_rate IS
  'Preferred stock coupon / stated dividend rate in percent per annum. '
  'XBRL: us-gaap:PreferredStockDividendRatePercentage (preferred source), '
  'us-gaap:PreferredStockDividendRatePerAnnum; falls back to OpenBB/yfinance or name parse';
COMMENT ON COLUMN raw.ticker_profile.liquidation_preference IS
  'Preferred stock liquidation preference per share. XBRL: '
  'us-gaap:PreferredStockLiquidationPreferenceValue / PreferredStockLiquidationPreference / '
  'TemporaryEquityLiquidationPreference(Value); falls back to '
  'us-gaap:PreferredStockParOrStatedValuePerShare, then name parse';
COMMENT ON COLUMN raw.ticker_profile.coupon_type IS
  'fixed | floating | fixed-to-floating; parsed from the security name (dei:SecurityTitle), '
  'not a standalone XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.fixed_period_end IS
  'End of the fixed-rate period parsed from the security name, not an XBRL us-gaap fact';
COMMENT ON COLUMN raw.ticker_profile.floating_spread IS
  'Floating-rate spread (percent) parsed from the security name, not an XBRL us-gaap fact';
COMMENT ON COLUMN raw.ticker_profile.tax_status IS
  'qualified | non-qualified | tax-exempt; parsed from the security name, not an XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.call_date IS
  'issuer call/redemption date parsed from the security name; XBRL concept '
  'PreferredStockRedemptionPricePerShare supplies the redemption price, not the date';
COMMENT ON COLUMN raw.ticker_profile.sector IS
  'Company sector from OpenBB/yfinance (provider metadata), not an XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.industry IS
  'Company industry from OpenBB/yfinance (provider metadata), not an XBRL fact';

-- Curated one-row-per-instrument profile. raw.ticker_profile remains the
-- source record; this relation preserves every contributing profile payload
-- while consolidating unambiguous attributes by issuer CIK and ticker.
CREATE TABLE IF NOT EXISTS clean.ticker_profile (
  cik VARCHAR(10) NOT NULL,
  ticker VARCHAR(32) NOT NULL,
  issuer_id BIGINT REFERENCES reference.issuers(issuer_id),
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  source_security_ids UUID[] NOT NULL,
  profile_count INTEGER NOT NULL,
  provider_sources TEXT[] NOT NULL DEFAULT '{}',
  issuer_name TEXT,
  security_name TEXT NOT NULL,
  security_type VARCHAR(32),
  classify_source VARCHAR(32),
  classify_confidence VARCHAR(16),
  profile_security_type TEXT,
  active BOOLEAN NOT NULL,
  dividend BOOLEAN NOT NULL,
  classification_conflict BOOLEAN NOT NULL DEFAULT FALSE,
  sector TEXT,
  industry TEXT,
  coupon_type VARCHAR(32),
  coupon_rate NUMERIC,
  fixed_period_end DATE,
  floating_spread NUMERIC,
  tax_status VARCHAR(32),
  call_date DATE,
  liquidation_preference NUMERIC,
  liquidation_preference_conflict BOOLEAN NOT NULL DEFAULT FALSE,
  metadata_conflicts JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_profiles JSONB NOT NULL DEFAULT '[]'::jsonb,
  cleaned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, ticker),
  CONSTRAINT chk_clean_ticker_profile_cik CHECK (cik ~ '^[0-9]{1,10}$'),
  CONSTRAINT chk_clean_ticker_profile_ticker CHECK (ticker = UPPER(BTRIM(ticker))),
  CONSTRAINT chk_clean_ticker_profile_security_type CHECK (
    security_type IS NULL OR security_type IN (
      'common_stock', 'preferred stock', 'debt', 'equity',
      'other_equity', 'other_debt', 'option', 'future', 'derivative',
      'government debt', 'corporate bond', 'other_debt_and_equity', 'other'
    )
  ),
  CONSTRAINT chk_clean_ticker_profile_source_count CHECK (
    profile_count > 0 AND cardinality(source_security_ids) > 0
  )
);

COMMENT ON TABLE clean.ticker_profile IS
  'Curated one-row-per-CIK-and-ticker view of raw profile records; retains every source ID and payload while surfacing unresolved conflicts';
COMMENT ON COLUMN clean.ticker_profile.cik IS
  'Zero-padded SEC issuer CIK used as part of the normalized instrument key';
COMMENT ON COLUMN clean.ticker_profile.ticker IS
  'Uppercase trimmed SEC-listed ticker used as part of the normalized instrument key';
COMMENT ON COLUMN clean.ticker_profile.issuer_id IS
  'Canonical reference.issuers identifier for the CIK, when resolved';
COMMENT ON COLUMN clean.ticker_profile.security_id IS
  'Reference security selected by active status, classifier confidence, evidence priority, and stable ID tie-break';
COMMENT ON COLUMN clean.ticker_profile.source_security_ids IS
  'All reference.securities IDs contributing to this consolidated CIK/ticker row';
COMMENT ON COLUMN clean.ticker_profile.profile_count IS
  'Number of raw.ticker_profile rows consolidated into this instrument row';
COMMENT ON COLUMN clean.ticker_profile.provider_sources IS
  'Distinct provider labels from all contributing raw profile rows';
COMMENT ON COLUMN clean.ticker_profile.issuer_name IS
  'Registrant name from reference.issuers, not a security-series title';
COMMENT ON COLUMN clean.ticker_profile.security_name IS
  'Security title from the selected reference.securities row';
COMMENT ON COLUMN clean.ticker_profile.security_type IS
  'Canonical classification from the selected reference.securities row';
COMMENT ON COLUMN clean.ticker_profile.classify_source IS
  'Classifier signal associated with the selected reference security';
COMMENT ON COLUMN clean.ticker_profile.classify_confidence IS
  'Confidence level associated with the selected reference security';
COMMENT ON COLUMN clean.ticker_profile.profile_security_type IS
  'Consensus provider-specific series description; NULL when contributing rows disagree';
COMMENT ON COLUMN clean.ticker_profile.active IS
  'Whether the selected reference security is currently active';
COMMENT ON COLUMN clean.ticker_profile.dividend IS
  'Dividend flag from the selected reference security';
COMMENT ON COLUMN clean.ticker_profile.classification_conflict IS
  'TRUE only when the highest-ranked classifier evidence ties across distinct security types; lower-ranked alternatives are retained in source_profiles';
COMMENT ON COLUMN clean.ticker_profile.sector IS
  'Consensus issuer sector from contributing profiles; NULL when unavailable or conflicting';
COMMENT ON COLUMN clean.ticker_profile.industry IS
  'Consensus issuer industry from contributing profiles; NULL when unavailable or conflicting';
COMMENT ON COLUMN clean.ticker_profile.coupon_type IS
  'Consensus preferred coupon structure parsed or reported by a profile source';
COMMENT ON COLUMN clean.ticker_profile.coupon_rate IS
  'Consensus stated preferred coupon or dividend rate, expressed as percent per annum';
COMMENT ON COLUMN clean.ticker_profile.fixed_period_end IS
  'Consensus end date of the preferred security fixed-rate period';
COMMENT ON COLUMN clean.ticker_profile.floating_spread IS
  'Consensus floating-rate spread, expressed as a percentage';
COMMENT ON COLUMN clean.ticker_profile.tax_status IS
  'Consensus tax treatment reported or parsed for the preferred security';
COMMENT ON COLUMN clean.ticker_profile.call_date IS
  'Consensus issuer call date, when supplied by a source';
COMMENT ON COLUMN clean.ticker_profile.liquidation_preference IS
  'Per-share liquidation preference retained only when all non-null source values agree';
COMMENT ON COLUMN clean.ticker_profile.liquidation_preference_conflict IS
  'TRUE when contributing profiles contain conflicting non-null liquidation preferences';
COMMENT ON COLUMN clean.ticker_profile.metadata_conflicts IS
  'JSONB map of attributes whose contributing source values disagree';
COMMENT ON COLUMN clean.ticker_profile.source_profiles IS
  'JSONB array preserving every contributing source security ID, provider, retrieval time, and raw payload';
COMMENT ON COLUMN clean.ticker_profile.cleaned_at IS
  'Timestamp when this curated snapshot was rebuilt';
CREATE INDEX IF NOT EXISTS ix_clean_ticker_profile_issuer_id
  ON clean.ticker_profile (issuer_id);
CREATE INDEX IF NOT EXISTS ix_clean_ticker_profile_security_id
  ON clean.ticker_profile (security_id);

CREATE TABLE IF NOT EXISTS clean.company_profile (
  profile_id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  parent_name TEXT NOT NULL,
  reference_security_id UUID REFERENCES reference.securities(security_id),
  source_profile_security_id UUID REFERENCES raw.ticker_profile(security_id),
  source_provider VARCHAR(64),
  source_retrieved_at TIMESTAMPTZ,
  ask NUMERIC, bid NUMERIC, fax TEXT, zip TEXT, beta NUMERIC, city TEXT,
  name TEXT, open NUMERIC, phone TEXT, state TEXT, market TEXT, region TEXT,
  sector TEXT, volume BIGINT, country TEXT, day_low NUMERIC, max_age BIGINT,
  website TEXT, address1 TEXT, address2 TEXT, ask_size BIGINT, bid_size BIGINT,
  currency TEXT, day_high NUMERIC, exchange TEXT, hq_state TEXT, industry TEXT,
  language TEXT, employees BIGINT, long_name TEXT, peg_ratio NUMERIC,
  tradeable BOOLEAN, type_disp TEXT, audit_risk BIGINT, board_risk BIGINT,
  book_value NUMERIC, hq_country TEXT, issue_type TEXT, market_cap BIGINT,
  price_hint BIGINT, quote_type TEXT, sector_key TEXT, short_name TEXT,
  total_cash BIGINT, total_debt BIGINT, company_url TEXT, eps_forward NUMERIC,
  forward_eps NUMERIC, forward_p_e NUMERIC, hq_address1 TEXT,
  quick_ratio NUMERIC, sector_disp TEXT, short_ratio NUMERIC,
  triggerable BOOLEAN, all_time_low NUMERIC, display_name TEXT,
  float_shares BIGINT, industry_key TEXT, market_state TEXT, overall_risk BIGINT,
  payout_ratio NUMERIC, shares_float BIGINT, shares_short BIGINT,
  trailing_eps NUMERIC, trailing_p_e NUMERIC, all_time_high NUMERIC,
  current_price NUMERIC, current_ratio NUMERIC, dividend_date DATE,
  dividend_rate NUMERIC, esg_populated BOOLEAN, fullday_price NUMERIC,
  gross_margins NUMERIC, gross_profits BIGINT, industry_disp TEXT,
  price_to_book NUMERIC, total_revenue BIGINT, pct_change_52w NUMERIC,
  average_volume BIGINT, debt_to_equity NUMERIC, dividend_yield NUMERIC,
  dividend_yield_fraction NUMERIC, dividend_yield_source_unit VARCHAR(32),
  ebitda_margins NUMERIC, fullday_change NUMERIC, previous_close NUMERIC,
  profit_margins NUMERIC, revenue_growth NUMERIC, stock_exchange TEXT,
  hq_address_city TEXT, pre_market_time TIMESTAMPTZ, source_interval BIGINT,
  crypto_tradeable BOOLEAN, enterprise_value BIGINT, eps_current_year NUMERIC,
  ex_dividend_date DATE, operating_cashflow BIGINT, recommendation_key TEXT,
  shares_outstanding BIGINT, date_short_interest DATE,
  fifty_two_week_high NUMERIC, full_time_employees BIGINT,
  last_dividend_value NUMERIC, most_recent_quarter DATE,
  recommendation_mean NUMERIC, regular_market_open NUMERIC,
  regular_market_time TIMESTAMPTZ, target_median_price NUMERIC,
  average_volume10days BIGINT, fifty_two_week_range TEXT,
  last_fiscal_year_end DATE, net_income_to_common BIGINT,
  next_fiscal_year_end DATE, regular_market_price NUMERIC,
  sand_p52_week_change NUMERIC, total_cash_per_share NUMERIC,
  enterprise_to_revenue NUMERIC, governance_epoch_date DATE,
  held_percent_insiders NUMERIC, regular_market_change NUMERIC,
  regular_market_volume BIGINT, average_analyst_rating TEXT,
  earnings_timestamp_end TIMESTAMPTZ, exchange_timezone_name TEXT,
  return_on_assets NUMERIC, return_on_equity NUMERIC, target_low_price NUMERIC,
  business_phone_no TEXT, compensation_risk BIGINT, fifty_day_average NUMERIC,
  industry_category TEXT, operating_margins NUMERIC, pre_market_change NUMERIC,
  quote_source_name TEXT, revenue_per_share NUMERIC, target_high_price NUMERIC,
  target_mean_price NUMERIC, earnings_timestamp DATE, fifty_two_week_low NUMERIC,
  financial_currency TEXT, full_exchange_name TEXT, last_dividend_date DATE,
  pre_market_price NUMERIC, message_board_id TEXT,
  c2_c3_leverage_exempt BOOLEAN GENERATED ALWAYS AS (
    COALESCE(UPPER(issue_type) = 'EQUITY' AND LOWER(sector_key) = 'real-estate', FALSE)
  ) STORED,
  source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_clean_company_profile_symbol_parent UNIQUE (symbol, parent_name),
  CONSTRAINT chk_clean_company_profile_symbol CHECK (
    symbol = UPPER(BTRIM(symbol)) AND symbol <> ''
  ),
  CONSTRAINT chk_clean_company_profile_parent CHECK (BTRIM(parent_name) <> '')
);
CREATE INDEX IF NOT EXISTS ix_clean_company_profile_reference_security_id
  ON clean.company_profile (reference_security_id);
CREATE INDEX IF NOT EXISTS ix_clean_company_profile_source_profile_security_id
  ON clean.company_profile (source_profile_security_id);

CREATE TABLE IF NOT EXISTS clean.company_officer (
  symbol TEXT NOT NULL,
  parent_name TEXT NOT NULL,
  officer_no SMALLINT NOT NULL,
  age SMALLINT,
  name TEXT NOT NULL,
  title TEXT,
  total_pay NUMERIC,
  year_born SMALLINT,
  fiscal_year SMALLINT,
  exercised_value NUMERIC,
  unexercised_value NUMERIC,
  officer_max_age SMALLINT,
  source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, parent_name, officer_no),
  CONSTRAINT uq_clean_company_officer_identity
    UNIQUE NULLS NOT DISTINCT (symbol, parent_name, name, title),
  CONSTRAINT fk_clean_company_officer_profile
    FOREIGN KEY (symbol, parent_name)
    REFERENCES clean.company_profile(symbol, parent_name)
    ON DELETE CASCADE
);

COMMENT ON TABLE clean.company_profile IS
  'One typed company-level vendor profile per symbol and parent name, loaded from raw OpenBB/yfinance profile payloads';
COMMENT ON TABLE clean.company_officer IS
  'Officer and compensation rows belonging to a clean company profile; missing compensation remains NULL';

DO $company_profile_comments$
DECLARE
  column_row RECORD;
  column_comment TEXT;
BEGIN
  FOR column_row IN
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = 'clean'
      AND table_name = 'company_profile'
  LOOP
    column_comment := CASE column_row.column_name
      WHEN 'profile_id' THEN 'Surrogate primary key for this clean company-profile row'
      WHEN 'symbol' THEN 'Uppercase provider ticker and first component of the company-profile key'
      WHEN 'parent_name' THEN 'Company name paired with symbol; referenced by the officer child table'
      WHEN 'reference_security_id' THEN 'Matching canonical listed-security ID when the symbol resolves in reference.securities'
      WHEN 'source_profile_security_id' THEN 'Raw ticker-profile security ID whose provider payload supplied this company record'
      WHEN 'source_provider' THEN 'Provider label on the raw profile source row'
      WHEN 'source_retrieved_at' THEN 'Retrieval timestamp of the selected raw profile source'
      WHEN 'pct_change_52w' THEN '52-week relative price change; source JSON key 52_week_change'
      WHEN 'dividend_yield' THEN 'Provider-native yield in percent points when supplied by OpenBB/YFinance; original value is preserved'
      WHEN 'dividend_yield_fraction' THEN 'Canonical decimal yield fraction, populated only when dividend_rate/current_price corroborates the source unit'
      WHEN 'dividend_yield_source_unit' THEN 'How source dividend_yield was interpreted: fraction, percent_points, ambiguous, or unverified'
      WHEN 'payout_ratio' THEN 'Provider-native payout ratio; no scaling is applied without source-unit confirmation'
      WHEN 'debt_to_equity' THEN 'Provider leverage multiple, not a percentage; raw provider value is preserved'
      WHEN 'quick_ratio' THEN 'Provider-native liquidity multiple, not a percentage'
      WHEN 'current_ratio' THEN 'Provider-native liquidity multiple, not a percentage'
      WHEN 'gross_margins' THEN 'Provider margin fraction where 0.25 represents 25 percent'
      WHEN 'ebitda_margins' THEN 'Provider margin fraction where 0.25 represents 25 percent'
      WHEN 'profit_margins' THEN 'Provider margin fraction where 0.25 represents 25 percent'
      WHEN 'operating_margins' THEN 'Provider margin fraction where 0.25 represents 25 percent'
      WHEN 'revenue_growth' THEN 'Provider growth fraction where 0.10 represents 10 percent'
      WHEN 'return_on_assets' THEN 'Provider return fraction where 0.05 represents 5 percent'
      WHEN 'return_on_equity' THEN 'Provider return fraction where 0.05 represents 5 percent'
      WHEN 'dividend_date' THEN 'Dividend date converted from the source Unix epoch seconds to a UTC calendar date'
      WHEN 'ex_dividend_date' THEN 'Ex-dividend date converted from the source Unix epoch seconds to a UTC calendar date'
      WHEN 'last_dividend_date' THEN 'Last dividend date converted from the source Unix epoch seconds to a UTC calendar date'
      WHEN 'earnings_timestamp' THEN 'Earnings date converted from the source Unix epoch seconds to a UTC calendar date'
      WHEN 'pre_market_time' THEN 'Pre-market quote time converted from Unix epoch seconds to a UTC timestamp'
      WHEN 'regular_market_time' THEN 'Regular-market quote time converted from Unix epoch seconds to a UTC timestamp'
      WHEN 'earnings_timestamp_end' THEN 'End of earnings-event window converted from Unix epoch seconds to a UTC timestamp'
      WHEN 'date_short_interest' THEN 'Short-interest report date converted from Unix epoch seconds to a UTC calendar date'
      WHEN 'most_recent_quarter' THEN 'Most recent fiscal-quarter end converted from Unix epoch seconds to a UTC calendar date'
      WHEN 'last_fiscal_year_end' THEN 'Last fiscal-year end converted from Unix epoch seconds to a UTC calendar date'
      WHEN 'next_fiscal_year_end' THEN 'Next fiscal-year end converted from Unix epoch seconds to a UTC calendar date'
      WHEN 'governance_epoch_date' THEN 'Governance data date converted from Unix epoch seconds to a UTC calendar date'
      WHEN 'c2_c3_leverage_exempt' THEN 'Generated tag for issue_type EQUITY and sector_key real-estate; informational only and does not change C2/C3 scoring'
      WHEN 'source_payload' THEN 'JSONB snapshot of selected scalar source fields; officer arrays are stored separately'
      WHEN 'loaded_at' THEN 'Timestamp when the clean company profile was loaded'
      ELSE format('Scalar OpenBB/yfinance company-profile attribute from source key %s', column_row.column_name)
    END;
    EXECUTE format(
      'COMMENT ON COLUMN clean.company_profile.%I IS %L',
      column_row.column_name,
      column_comment
    );
  END LOOP;

  COMMENT ON COLUMN clean.company_officer.symbol IS
    'Company symbol; first component of the composite foreign key to clean.company_profile';
  COMMENT ON COLUMN clean.company_officer.parent_name IS
    'Parent company name; second component of the composite foreign key to clean.company_profile';
  COMMENT ON COLUMN clean.company_officer.officer_no IS
    'One-based ordinal from the source company_officers array; child-row key within the parent profile';
  COMMENT ON COLUMN clean.company_officer.age IS
    'Officer age when reported; NULL when unavailable';
  COMMENT ON COLUMN clean.company_officer.name IS
    'Officer name as reported by the provider';
  COMMENT ON COLUMN clean.company_officer.title IS
    'Officer title as reported by the provider';
  COMMENT ON COLUMN clean.company_officer.total_pay IS
    'Reported officer total compensation; NULL when the source omitted pay, distinct from zero';
  COMMENT ON COLUMN clean.company_officer.year_born IS
    'Officer birth year when reported';
  COMMENT ON COLUMN clean.company_officer.fiscal_year IS
    'Fiscal year associated with this officer record';
  COMMENT ON COLUMN clean.company_officer.exercised_value IS
    'Reported value of exercised awards or options; NULL when unavailable';
  COMMENT ON COLUMN clean.company_officer.unexercised_value IS
    'Reported value of unexercised awards or options; NULL when unavailable';
  COMMENT ON COLUMN clean.company_officer.officer_max_age IS
    'Source officer_max_age flag/value preserved from the provider row';
  COMMENT ON COLUMN clean.company_officer.source_payload IS
    'Original officer JSON object for audit and future reprocessing';
  COMMENT ON COLUMN clean.company_officer.loaded_at IS
    'Timestamp when this officer row was loaded';
END
$company_profile_comments$;

CREATE TABLE IF NOT EXISTS raw.dividend_data (
  security_id UUID REFERENCES reference.securities(security_id),
  ex_dividend_date DATE NOT NULL, declaration_date DATE, record_date DATE,
  payment_date DATE, amount NUMERIC, adjusted_amount NUMERIC,
  frequency VARCHAR(32), currency VARCHAR(8), provider VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(security_id, ex_dividend_date, provider)
);

COMMENT ON COLUMN raw.dividend_data.amount IS
  'Per-share dividend amount. XBRL: us-gaap:CommonStockDividendsPerShareDeclared / '
  'us-gaap:PreferredStockDividendsPerShare; aggregate fallbacks (DividendsCommonStockCash, '
  'PaymentsOfDividends, ...) kept only when no per-share declaration was filed';
COMMENT ON COLUMN raw.dividend_data.ex_dividend_date IS
  'Dividend period. XBRL: fact.end (xbrl:periodEnd) is the proxy; SEC XBRL does not '
  'expose an ex-date fact, iXBRL filing narrative carries the true ex/record/payment dates';
COMMENT ON COLUMN raw.dividend_data.declaration_date IS
  'Declaration date from iXBRL filing narrative (ix:declarationDate), not a companyfacts fact';
COMMENT ON COLUMN raw.dividend_data.record_date IS
  'Record date from iXBRL filing narrative (ix:recordDate), not a companyfacts fact';
COMMENT ON COLUMN raw.dividend_data.payment_date IS
  'Payment date from iXBRL filing narrative (ix:paymentDate); companyfacts fact end is the fallback';
COMMENT ON COLUMN raw.dividend_data.frequency IS
  'Dividend frequency (Annual/Quarterly/Monthly). Inferred; not an XBRL us-gaap fact';
COMMENT ON COLUMN raw.dividend_data.currency IS
  'Currency of the dividend amount, derived from the XBRL unit (e.g. USD per share)';

-- Issuer-level XBRL company facts. One row per SEC CIK: the full
-- companyfacts payload describes the ISSUER, not one listed series, so it is
-- stored exactly once keyed by cik instead of being copied once per
-- reference.securities row (1000+ redundant copies were being written for
-- issuers with many listed series such as BAC or PSA). Reference securities
-- link to this payload through their cik column.
CREATE TABLE IF NOT EXISTS raw.companyfacts (
  cik VARCHAR(20) PRIMARY KEY,
  company_name TEXT,
  concept_groups JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_payload JSONB NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'SEC_XBRL',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.companyfacts IS
  'us-gaap/dei facts fetched once per CIK (data.sec.gov/api/xbrl/companyfacts); '
  'keyed by CIK so issuer-level payloads are never duplicated per security';

-- Taxonomy-scoped XBRL concept facts (per-concept companyconcept payloads).
-- One row per issuer CIK; every listed security of the issuer shares the row
-- through reference.securities.cik.
CREATE TABLE IF NOT EXISTS raw.company_taxonomy (
  cik VARCHAR(20) PRIMARY KEY,
  company_name TEXT,
  taxonomies JSONB NOT NULL DEFAULT '{}'::jsonb,
  concept_groups JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash VARCHAR(64) NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'SEC_XBRL',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.company_taxonomy IS
  'Preferred-stock concepts fetched via the XBRL Data API companyconcept endpoint, '
  'keyed by CIK (one issuer row shared by all of its listed securities)';

-- Issuer submissions history. One row per CIK: the submissions payload is
-- issuer-level and stored exactly once (see raw.companyfacts).
CREATE TABLE IF NOT EXISTS raw.sec_submissions (
  cik VARCHAR(20) PRIMARY KEY,
  company_name TEXT,
  raw_payload JSONB NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  provider VARCHAR(64) NOT NULL DEFAULT 'SEC_SUBMISSIONS',
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.sec_submissions IS
  'SEC submissions history fetched once per CIK (data.sec.gov/submissions); '
  'keyed by CIK so the issuer payload is never duplicated per security';

-- Compact per-CIK classification cache. Built by stage 0
-- (scripts.populate_raw_tables) from the full companyfacts payload and reused
-- by stage 1 (populate_reference_tables) and stage 3 (populate_companyfacts)
-- so the same full issuer JSON is downloaded at most once per pipeline run.
CREATE TABLE IF NOT EXISTS raw.company_classification (
  cik VARCHAR(20) PRIMARY KEY,
  ticker VARCHAR(32) NOT NULL,
  company_name TEXT,
  security_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  security_titles JSONB NOT NULL DEFAULT '[]'::jsonb,
  security_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
  dividend_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
  dividend BOOLEAN NOT NULL DEFAULT FALSE,
  dividend_last_paid DATE,
  status VARCHAR(32) NOT NULL DEFAULT 'unavailable',
  content_hash VARCHAR(64),
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.company_classification IS
  'Cached output of classify_companyfacts() per CIK; prevents re-downloading '
  'the full companyfacts payload by populate_reference_tables / populate_companyfacts';

COMMENT ON COLUMN raw.company_classification.security_titles IS
  'dei:SecurityTitle or dei:Security12bTitle values extracted from the '
  'companyfacts payload, used to populate reference.securities.security_name';

CREATE TABLE IF NOT EXISTS raw.sec_documents (
  document_id BIGSERIAL PRIMARY KEY, security_id UUID REFERENCES reference.securities(security_id),
  cik VARCHAR(20), accession_no VARCHAR(64), form_type VARCHAR(32),
  filing_date DATE, report_date DATE, primary_document TEXT, source_url TEXT,
  concept_groups JSONB NOT NULL DEFAULT '{}'::jsonb,
  retrieved_at TIMESTAMPTZ DEFAULT now(), content_hash VARCHAR(64), raw_text TEXT
);

-- Per-security rows may legitimately share identical concept-group hashes
-- (e.g. two preferred series under the same issuer CIK), so content_hash is
-- indexed but not globally unique.
CREATE INDEX IF NOT EXISTS ix_sec_documents_content_hash
ON raw.sec_documents(content_hash);

-- One concept-index row per security. Multiple textual filings per security
-- remain possible: NULL security_id rows are not constrained.
CREATE UNIQUE INDEX IF NOT EXISTS ux_sec_documents_security
ON raw.sec_documents(security_id) WHERE security_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_sec_documents_cik
ON raw.sec_documents(cik);

-- dei security titles paired to the SEC trading symbol they name, parsed from
-- the filing XBRL financial-report instance (*_htm.xml). SEC's companyfacts
-- JSON never exposes dei:SecurityTitle/dei:Security12bTitle (only an allowlist
-- of dei concepts), so the cover-page titles are read straight out of the
-- instance document, where dei:TradingSymbol and dei:Security12bTitle sit
-- side-by-side per registered class. One current row per (cik, ticker); the
-- classifier consumes these as the exact bound title for the instrument.
CREATE TABLE IF NOT EXISTS raw.sec_instrument_titles (
  cik VARCHAR(20) NOT NULL,
  ticker VARCHAR(32) NOT NULL,
  title TEXT NOT NULL,
  accession_no VARCHAR(64),
  filing_date DATE,
  form_type VARCHAR(32),
  source_url TEXT,
  document_hash VARCHAR(64),
  content_hash VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, ticker)
);

COMMENT ON TABLE raw.sec_instrument_titles IS
  'Per-class dei cover-page security titles parsed from filing XBRL instances, '
  'paired to the issuing SEC ticker symbol (one row per cik+ticker)';

CREATE INDEX IF NOT EXISTS ix_sec_instrument_titles_cik
ON raw.sec_instrument_titles(cik);

-- Dividend universe: the gating set used by every downstream ETL stage.
CREATE INDEX IF NOT EXISTS ix_securities_dividend_active
ON reference.securities (ticker)
WHERE dividend = TRUE AND active = TRUE;

CREATE TABLE IF NOT EXISTS preferred.security_terms (
  security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
  preferred_series VARCHAR(128),
  dividend_rate NUMERIC, liquidation_preference NUMERIC,
  source_document_id BIGINT REFERENCES raw.sec_documents(document_id),
  confidence_score NUMERIC, reviewed_by TEXT, reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_security_terms_source_document_id
  ON preferred.security_terms (source_document_id);

COMMENT ON COLUMN preferred.security_terms.dividend_rate IS
  'Preferred dividend rate (percent/amount). XBRL: us-gaap:PreferredStockDividendRatePercentage '
  '(seeded from the latest raw.dividend_data amount when no XBRL rate was filed)';
COMMENT ON COLUMN preferred.security_terms.liquidation_preference IS
  'XBRL: us-gaap:PreferredStockLiquidationPreferenceValue / PreferredStockLiquidationPreference / '
  'TemporaryEquityLiquidationPreference(Value); fallback PreferredStockParOrStatedValuePerShare';
COMMENT ON COLUMN preferred.security_terms.preferred_series IS
  'Series label parsed from dei:SecurityTitle (e.g. "Series C Preferred Stock")';

-- Issuer-level SEC XBRL preferred terms, recovered from the payloads that
-- scripts.populate_preferred_profiles.py stores in raw.ticker_profile.
--
-- SEC Company Facts are filed per *issuer*, not per registered series, so a
-- coupon rate or liquidation amount read from them describes the whole issuer
-- and cannot be attributed to one preferred class. That is precisely why the
-- per-series term columns on clean.ticker_profile are left NULL instead of
-- being filled from here: copying one issuer-level figure onto every series of
-- a multi-series issuer would assert a precision the source does not have.
-- This view makes the evidence visible without that leap.
--
-- Read terms_scope and security_count before using a value: when
-- security_count > 1 the row describes the issuer, not any single security.
CREATE OR REPLACE VIEW preferred.issuer_terms AS
SELECT
    LPAD(BTRIM(s.cik), 10, '0') AS cik,
    i.issuer_name,
    MIN((tp.raw_payload #>> '{sec_xbrl,coupon_rate}')::NUMERIC)
        AS issuer_coupon_rate_pct,
    MIN((tp.raw_payload #>> '{sec_xbrl,liquidation_preference}')::NUMERIC)
        AS issuer_liquidation_or_par_value,
    COUNT(DISTINCT s.security_id) AS security_count,
    COUNT(DISTINCT tp.raw_payload #>> '{sec_xbrl,coupon_rate}')
        AS distinct_coupon_values,
    COUNT(DISTINCT tp.raw_payload #>> '{sec_xbrl,liquidation_preference}')
        AS distinct_liquidation_values,
    'issuer_level_unallocated'::TEXT AS terms_scope
FROM raw.ticker_profile AS tp
JOIN reference.securities AS s ON s.security_id = tp.security_id
LEFT JOIN reference.issuers AS i ON i.issuer_id = s.issuer_id
WHERE NULLIF(BTRIM(s.cik), '') IS NOT NULL
  AND tp.raw_payload ? 'sec_xbrl'
GROUP BY LPAD(BTRIM(s.cik), 10, '0'), i.issuer_name;

COMMENT ON VIEW preferred.issuer_terms IS
  'SEC XBRL preferred terms at ISSUER granularity, extracted per CIK by '
  'scripts.populate_preferred_profiles.py and stored under '
  'raw.ticker_profile.raw_payload->sec_xbrl. Not attributable to a single '
  'preferred series: SEC Company Facts carry no member dimension. Exposed as '
  'a view so the evidence is auditable without promoting issuer-level figures '
  'into the per-series columns of clean.ticker_profile, which stay NULL by '
  'design.';
COMMENT ON COLUMN preferred.issuer_terms.cik IS
  'Zero-padded 10-digit issuer CIK the terms were filed under';
COMMENT ON COLUMN preferred.issuer_terms.issuer_coupon_rate_pct IS
  'Issuer coupon rate, percent per annum, from the preferred dividend-rate '
  'XBRL concepts. Issuer-level: describes the issuer, not one series. NULL '
  'when the issuer never reported the concept. Not validated: observed '
  'values include implausible rates (up to 90%), so the concept selected for '
  'an issuer may not be a preferred dividend rate at all. Sanity-check the '
  'plausibility of any value before use';
COMMENT ON COLUMN preferred.issuer_terms.issuer_liquidation_or_par_value IS
  'Deliberately NOT named "liquidation preference", and NOT guaranteed to be a '
  'per-share amount. extract_preferred_terms_from_companyfacts falls back to '
  'the par/stated-value concepts when no liquidation-preference concept is '
  'filed and stores both under one key. Observed values mix at least three '
  'incomparable things: real per-share liquidation preferences, par values '
  '(mostly <10, including common-stock par artifacts from issuers with no '
  'preferred outstanding), and issuer-level AGGREGATE dollar totals across all '
  'classes (e.g. one 17-series issuer reports 4.35e9, which is not a per-share '
  'figure). Treat magnitude as meaningless and corroborate against '
  'preferred.security_terms or preferred.contract_terms, which are per-security, '
  'before treating anything here as a liquidation preference';
COMMENT ON COLUMN preferred.issuer_terms.security_count IS
  'Number of securities sharing this CIK. Greater than one means the row '
  'describes the issuer rather than any individual instrument';
COMMENT ON COLUMN preferred.issuer_terms.distinct_coupon_values IS
  'Distinct coupon values seen across this issuer securities; > 1 would mean '
  'the per-security extraction disagreed';
COMMENT ON COLUMN preferred.issuer_terms.distinct_liquidation_values IS
  'Distinct liquidation/par values seen across this issuer securities; > 1 '
  'would mean the per-security extraction disagreed';
COMMENT ON COLUMN preferred.issuer_terms.terms_scope IS
  'Constant issuer_level_unallocated: marks these values as issuer-scoped '
  'evidence that must not be joined onto a single preferred series';

-- Narrative contract documents (Certificate of Designation exhibits in 8-Ks,
-- and prospectus / prospectus supplement filings), fetched by
-- scripts/populate_contract_terms.py for clause extraction. Stored in raw
-- (one row per document, not per security) so the full text can be re-mined.
CREATE TABLE IF NOT EXISTS raw.contract_documents (
  document_id BIGSERIAL PRIMARY KEY,
  security_id UUID REFERENCES reference.securities(security_id),
  cik VARCHAR(20),
  form_type VARCHAR(32),
  filing_date DATE,
  accession_no VARCHAR(64),
  primary_document TEXT,
  exhibit_type VARCHAR(64),
  source_url TEXT,
  raw_text TEXT,
  content_hash VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_contract_documents_security_id
  ON raw.contract_documents (security_id);

COMMENT ON TABLE raw.contract_documents IS
  'Narrative filings used to mine preferred-stock contractual clauses: '
  'Certificate of Designation exhibits (Form 8-K Exhibit 3.1/3.2) and '
  'prospectus supplements (424B5/424B3, S-1/S-3)';

CREATE INDEX IF NOT EXISTS ix_contract_documents_security
ON raw.contract_documents(security_id);

CREATE INDEX IF NOT EXISTS ix_contract_documents_cik
ON raw.contract_documents(cik);

-- Per-security contractual terms mined from narrative SEC filings. Distinct
-- from preferred.security_terms (XBRL/dividend-screen values): this table
-- holds the authoritative amounts read straight out of the governing
-- documents, with the source document and the exact snippet as evidence.
CREATE TABLE IF NOT EXISTS preferred.contract_terms (
  security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
  liquidation_preference NUMERIC,
  call_price NUMERIC,
  first_call_date DATE,
  redemption_schedule JSONB NOT NULL DEFAULT '[]'::jsonb,
  optional_redemption BOOLEAN NOT NULL DEFAULT FALSE,
  source_document_id BIGINT REFERENCES raw.contract_documents(document_id),
  sections JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence NUMERIC,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_contract_terms_source_document_id
  ON preferred.contract_terms (source_document_id);

COMMENT ON COLUMN preferred.contract_terms.liquidation_preference IS
  'Liquidation Preference amount, per share, read from the governing document '
  '(e.g. "$25.00 per share")';
COMMENT ON COLUMN preferred.contract_terms.call_price IS
  'Optional redemption call price, per share, at the first call date '
  '(e.g. "$26.5625 per share")';
COMMENT ON COLUMN preferred.contract_terms.first_call_date IS
  'Earliest date the issuer may redeem (the "First Call Date" / "on or after" date)';
COMMENT ON COLUMN preferred.contract_terms.redemption_schedule IS
  'Optional redemption price schedule: [{"effective_date": "...", "price": ...}]';
COMMENT ON COLUMN preferred.contract_terms.sections IS
  'Evidence: the section heading and matched snippet for each mined clause';

-- Per-security snapshot of SEC XBRL dividend evidence, built by
-- scripts/sec_xbrl_dividend_tags.py from raw.companyfacts.
CREATE TABLE IF NOT EXISTS preferred.dividend_snapshot (
  security_id UUID PRIMARY KEY REFERENCES reference.securities(security_id),
  ticker VARCHAR(32) NOT NULL,
  cik VARCHAR(20),
  preferred_flag BOOLEAN NOT NULL DEFAULT FALSE,
  pays_dividend BOOLEAN,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  dividend_evidence_tag TEXT,
  latest_dividend_period_end DATE,
  latest_dividend_filed DATE,
  latest_dividend_form VARCHAR(32),
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE preferred.dividend_snapshot
  ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN preferred.dividend_snapshot.pays_dividend IS
  'TRUE: the issuer has positive dividend evidence in the stored companyfacts '
  'payload; the snapshot stores only such (preferred) issuers';
COMMENT ON COLUMN preferred.dividend_snapshot.active IS
  'TRUE: a positive dividend fact was reported within the recent lookback '
  'window (actively issuing); FALSE: historical dividend evidence exists but '
  'the issuer is not actively paying';
COMMENT ON COLUMN preferred.dividend_snapshot.dividend_evidence_tag IS
  'XBRL/Inline XBRL tag that supplied the dividend evidence, e.g. '
  'us-gaap:CommonStockDividendsPerShareDeclared';

-- Periodic statements are versioned: one row per (period, filing state), not
-- one row per period. A period is reported in its original filing and again in
-- every later filing that repeats it as a comparative, and may be restated, so
-- the relation has to keep every vintage to be queryable point-in-time. A
-- consumer picks the latest row whose filed date is at or before the date it is
-- evaluating. Collapsing to the most recently filed value -- which is what this
-- table did before V0009 -- makes it impossible to ask what was known on a past
-- date at all. Mirrors V0009_periodic_financials_filing_date.sql; facts with no
-- filing date are dropped rather than assumed available.
CREATE TABLE IF NOT EXISTS fundamentals.periodic_financials (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  period_end DATE NOT NULL, fiscal_year INT, fiscal_period VARCHAR(16),
  filed DATE NOT NULL,
  revenue NUMERIC, operating_income NUMERIC, net_income NUMERIC, eps NUMERIC,
  cash NUMERIC, assets NUMERIC, liabilities NUMERIC, debt NUMERIC, equity NUMERIC,
  -- V0016: the current-basis subtotals, stored separately. They were previously
  -- XBRL fallbacks for `assets`/`liabilities`, which mixed two accounting bases
  -- in one column and left assets = liabilities + equity broken on 44,630 rows.
  current_assets NUMERIC, current_liabilities NUMERIC,
  -- V0018: the contractual debt maturity ladder (year one, months 13-24).
  -- 2,748 and 2,740 of 7,079 stored companyfacts disclose these respectively,
  -- contrary to the specification's claim that XBRL does not expose them.
  debt_maturing_12m NUMERIC, debt_maturing_year_2 NUMERIC,
  committed_undrawn_facility NUMERIC,
  operating_cash_flow NUMERIC, capital_expenditures NUMERIC, free_cash_flow NUMERIC,
  -- V0011: the inputs the leverage ratios need, populated from the stored XBRL
  -- payload. Stored because they are reported; EBITDA is derived at feature
  -- time rather than persisted here.
  depreciation_amortization NUMERIC, interest_expense NUMERIC,
  shares_outstanding NUMERIC,
  source VARCHAR(64), retrieved_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(security_id, period_end, fiscal_period, filed)
);

CREATE TABLE IF NOT EXISTS model.features (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, current_price NUMERIC, annualized_dividend NUMERIC,
  dividend_yield NUMERIC, dividend_growth NUMERIC, earnings_payout NUMERIC,
  fcf_payout NUMERIC, dividend_coverage NUMERIC, debt_to_ebitda NUMERIC,
  interest_coverage NUMERIC, volatility_252d NUMERIC, momentum_252d NUMERIC,
  momentum_63d NUMERIC, liquidation_discount NUMERIC, legal_rights_score NUMERIC,
  data_quality_score NUMERIC, target_sustainable_dividend INT,
  -- V0016: quick_liquidity = cash / current_liabilities, from the current-basis
  -- columns V0016 adds above. Consumed by the CVS (regime.py CVS_WEIGHTS); not
  -- a declared ML feature, for the same reason debt_to_ebitda is not until V0012.
  quick_liquidity NUMERIC,
  -- V0018: maturity cliff over cash. Feeds circuit breaker C4 and the CVS.
  refinancing_wall NUMERIC,
  PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS model.scores (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, dividend_income_score NUMERIC,
  sustainability_score NUMERIC, legal_rights_score NUMERIC,
  appreciation_score NUMERIC, risk_score NUMERIC, valuation_score NUMERIC,
  composite_score NUMERIC, score_coverage NUMERIC(6,4),
  PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS model.predictions (
  run_id UUID NOT NULL, security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, probability NUMERIC, predicted_class INT,
  precision_threshold NUMERIC, model_version VARCHAR(64),
  feature_version VARCHAR(64), data_version VARCHAR(64),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(run_id, security_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS ix_predictions_security_id
  ON model.predictions (security_id);

-- The current prediction for each security and as-of date. Read this instead of
-- model.predictions directly: that table accumulates a complete set of rows per
-- run, so several conflicting sets can exist for the same (security_id,
-- as_of_date) and an unfiltered query returns an arbitrary one. Resolution is
-- per security rather than per run, because a newer run may cover only part of
-- an older date (feature carry-forward writes a few rows at earlier dates) and
-- dropping the remainder would hide securities that still have a current
-- prediction there.
--
-- Superseded runs are deliberately retained in model.predictions as the audit
-- trail of which model produced which number; pruning them is a retention
-- decision, taken separately. V0043 defined this per run, which shadowed the
-- fuller runs beneath a newer partial one; V0044 corrected it.
CREATE OR REPLACE VIEW model.current_predictions AS
SELECT DISTINCT ON (p.security_id, p.as_of_date) p.*
FROM model.predictions p
ORDER BY p.security_id, p.as_of_date, p.created_at DESC, p.run_id;

CREATE TABLE IF NOT EXISTS model.rankings (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, rank INT, composite_score NUMERIC, probability NUMERIC,
  PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS audit.source_lineage (
  lineage_id BIGSERIAL PRIMARY KEY, security_id UUID REFERENCES reference.securities(security_id),
  field_name TEXT NOT NULL, field_value TEXT, source TEXT, source_document TEXT,
  filing_date DATE, period DATE, retrieval_date TIMESTAMPTZ DEFAULT now(),
  provider TEXT, confidence_score NUMERIC
);
CREATE INDEX IF NOT EXISTS ix_source_lineage_security_id
  ON audit.source_lineage (security_id);

CREATE TABLE IF NOT EXISTS audit.data_quality (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, source_reliability NUMERIC, completeness NUMERIC,
  recency NUMERIC, consistency NUMERIC, quality_score NUMERIC, status VARCHAR(32),
  PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS audit.model_runs (
  run_id UUID PRIMARY KEY, model_version VARCHAR(64), feature_version VARCHAR(64),
  data_version VARCHAR(64), training_start DATE, training_end DATE,
  test_start DATE, test_end DATE, precision NUMERIC, recall NUMERIC, f1 NUMERIC,
  pr_auc NUMERIC, roc_auc NUMERIC, accuracy NUMERIC, parameters JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.nightly_runs (
  run_id BIGSERIAL PRIMARY KEY,
  run_date DATE NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'manual',   -- manual | airflow | systemd
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  exit_code INT,
  stages JSONB NOT NULL DEFAULT '{}',       -- {module: ok|failed|skipped}
  status TEXT NOT NULL DEFAULT 'running',   -- running | success | failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- V0038. Known-wrong values left in place and excluded from downstream use.
-- Append-only: a quarantined value is never deleted from its own table, and its
-- resolution is recorded here by setting resolved_at.
CREATE TABLE IF NOT EXISTS audit.quarantined_values (
  quarantine_id BIGSERIAL PRIMARY KEY,
  table_schema VARCHAR(64) NOT NULL,
  table_name VARCHAR(64) NOT NULL,
  column_name VARCHAR(64) NOT NULL,
  row_key TEXT NOT NULL,                  -- PK of the offending row, as text
  cik VARCHAR(10),
  ticker VARCHAR(16),
  observed_value TEXT NOT NULL,           -- the quarantined value, verbatim
  reason TEXT NOT NULL,                   -- why it cannot be trusted
  rule TEXT NOT NULL,                     -- the predicate that detected it
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,                -- NULL while still quarantined
  resolution_note TEXT,
  UNIQUE (table_schema, table_name, column_name, row_key, observed_value)
);

CREATE TABLE IF NOT EXISTS audit.nightly_checks (
  check_id BIGSERIAL PRIMARY KEY,
  verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_date DATE NOT NULL,
  verified_by TEXT NOT NULL DEFAULT 'single-owner',
  status TEXT NOT NULL,                     -- ok | attention
  findings JSONB NOT NULL DEFAULT '{}',
  notes TEXT
);

-- Descriptions for the project-owned relations. Column descriptions for
-- baseline fields are kept beside the canonical schema; V0024 applies the
-- same comments to existing databases and documents migration-added fields.
COMMENT ON TABLE audit.model_runs IS
  'One row per model evaluation run, including test metrics, baseline comparisons, and the readiness gate result';
COMMENT ON TABLE audit.nightly_checks IS
  'Auditable result of each nightly data-health verification pass';
COMMENT ON TABLE audit.nightly_runs IS
  'Execution summary for each scheduled or manual ETL pipeline run';
COMMENT ON TABLE audit.source_lineage IS
  'Field-level provenance for security attributes, including source, provider, filing period, and confidence';
COMMENT ON TABLE fundamentals.periodic_financials IS
  'SEC-reported financial statement facts by security, fiscal period, and filing vintage';
COMMENT ON TABLE model.features IS
  'Derived model inputs and target label snapshot for one security and as-of date';
COMMENT ON TABLE model.predictions IS
  'Model output for one security and as-of date, grouped by immutable run and version identifiers. Append-only across runs: re-scoring a date leaves every prior run in place, so query model.current_predictions for the current prediction';
COMMENT ON VIEW model.current_predictions IS
  'For each security and as_of_date, the prediction from the most recent run that has a row for it';
COMMENT ON TABLE model.rankings IS
  'Security ordering and published composite score for one screening date';
COMMENT ON TABLE model.scores IS
  'Component scores, composite score, and market-regime risk adjustments per security and date';
COMMENT ON TABLE preferred.contract_terms IS
  'Series-specific contractual redemption terms extracted from governing SEC filings with supporting evidence';
COMMENT ON TABLE preferred.dividend_snapshot IS
  'Per-security snapshot of preferred-stock classification and SEC dividend evidence';
COMMENT ON TABLE preferred.security_terms IS
  'Preferred-security rate and liquidation terms with their source and review metadata';
COMMENT ON TABLE raw.contract_documents IS
  'Stored text of SEC certificates and prospectus filings used to extract preferred contractual terms';
COMMENT ON TABLE raw.dividend_data IS
  'Normalized dividend events per security and provider, including source dates and amounts';
COMMENT ON TABLE raw.market_data IS
  'Daily security price and volume observations as supplied by market-data providers';
COMMENT ON TABLE raw.sec_documents IS
  'Indexed SEC filing documents and extracted concept groups associated with listed securities';
COMMENT ON TABLE raw.sec_instrument_titles IS
  'Latest SEC cover-page security title paired to its issuer CIK and trading ticker';
COMMENT ON TABLE raw.ticker_profile IS
  'Provider profile and preferred-security terms captured for one listed security';
COMMENT ON TABLE reference.exchanges IS
  'Canonical exchange codes and display names used by listed securities';
COMMENT ON TABLE reference.issuers IS
  'Canonical SEC registrants keyed by issuer ID and CIK';
COMMENT ON TABLE reference.securities IS
  'Canonical listed instruments keyed by security ID, with issuer, classification, and per-security attributes';

COMMENT ON COLUMN audit.nightly_checks.check_id IS
  'Surrogate key for one verification record';
COMMENT ON COLUMN audit.nightly_checks.verified_at IS
  'Timestamp when the verification was completed';
COMMENT ON COLUMN audit.nightly_checks.run_date IS
  'ET calendar date whose nightly pipeline health was checked';
COMMENT ON COLUMN audit.nightly_checks.verified_by IS
  'Actor or process that recorded the verification';
COMMENT ON COLUMN audit.nightly_checks.status IS
  'Overall verification result: ok or attention';
COMMENT ON COLUMN audit.nightly_checks.findings IS
  'Structured JSON results from the individual health checks';
COMMENT ON COLUMN audit.nightly_checks.notes IS
  'Optional human-readable context for the verification result';

COMMENT ON COLUMN audit.nightly_runs.run_id IS
  'Surrogate key for one ETL execution';
COMMENT ON COLUMN audit.nightly_runs.run_date IS
  'ET calendar date assigned to this nightly execution';
COMMENT ON COLUMN audit.nightly_runs.trigger IS
  'Execution origin, such as manual, airflow, or systemd';
COMMENT ON COLUMN audit.nightly_runs.started_at IS
  'Timestamp when the pipeline execution began';
COMMENT ON COLUMN audit.nightly_runs.finished_at IS
  'Timestamp when the pipeline execution ended; NULL while running';
COMMENT ON COLUMN audit.nightly_runs.exit_code IS
  'Process exit code; zero indicates success';
COMMENT ON COLUMN audit.nightly_runs.stages IS
  'JSON object mapping each ETL stage to its status';
COMMENT ON COLUMN audit.nightly_runs.status IS
  'Overall execution state: running, success, or failed';
COMMENT ON COLUMN audit.nightly_runs.created_at IS
  'Timestamp when this execution record was created';

COMMENT ON COLUMN preferred.contract_terms.security_id IS
  'References reference.securities; one contractual-terms row per listed security';
COMMENT ON COLUMN preferred.contract_terms.optional_redemption IS
  'Whether the governing terms grant the issuer an optional redemption right';
COMMENT ON COLUMN preferred.contract_terms.source_document_id IS
  'References the stored SEC filing that supplied the extracted terms';
COMMENT ON COLUMN preferred.contract_terms.confidence IS
  'Mean extraction confidence for the clauses found, on a zero-to-one scale; NULL when no clause was scored';
COMMENT ON COLUMN preferred.contract_terms.updated_at IS
  'Timestamp when the extracted contract terms were last written';

COMMENT ON COLUMN raw.contract_documents.document_id IS
  'Surrogate key for one stored filing document';
COMMENT ON COLUMN raw.contract_documents.security_id IS
  'Listed security associated with the document; NULL when the filing is issuer-wide';
COMMENT ON COLUMN raw.contract_documents.cik IS
  'SEC CIK of the registrant that filed the document';
COMMENT ON COLUMN raw.contract_documents.form_type IS
  'SEC filing form, such as 8-K, 424B5, S-1, or S-3';
COMMENT ON COLUMN raw.contract_documents.filing_date IS
  'Date the filing was submitted to SEC';
COMMENT ON COLUMN raw.contract_documents.accession_no IS
  'SEC accession number identifying the filing submission';
COMMENT ON COLUMN raw.contract_documents.primary_document IS
  'Primary filing or exhibit filename stored from the SEC archive';
COMMENT ON COLUMN raw.contract_documents.exhibit_type IS
  'SEC exhibit designation when the document is a filing exhibit';
COMMENT ON COLUMN raw.contract_documents.source_url IS
  'SEC archive URL from which the document was retrieved';
COMMENT ON COLUMN raw.contract_documents.raw_text IS
  'Extracted filing text used by the preferred-contract clause parsers';
COMMENT ON COLUMN raw.contract_documents.content_hash IS
  'SHA-256 hash of the stored document text for change detection';
COMMENT ON COLUMN raw.contract_documents.retrieved_at IS
  'Timestamp when the document text was retrieved or stored';

COMMENT ON COLUMN raw.sec_instrument_titles.cik IS
  'SEC Central Index Key of the issuer filing the cover page';
COMMENT ON COLUMN raw.sec_instrument_titles.ticker IS
  'Trading symbol paired with the title on the SEC filing cover page';
COMMENT ON COLUMN raw.sec_instrument_titles.title IS
  'Class-specific dei:SecurityTitle or dei:Security12bTitle value';
COMMENT ON COLUMN raw.sec_instrument_titles.accession_no IS
  'SEC accession number of the filing instance that supplied the title';
COMMENT ON COLUMN raw.sec_instrument_titles.filing_date IS
  'Date the title source filing was submitted';
COMMENT ON COLUMN raw.sec_instrument_titles.form_type IS
  'SEC form type of the title source filing';
COMMENT ON COLUMN raw.sec_instrument_titles.source_url IS
  'SEC archive URL of the XBRL filing instance';
COMMENT ON COLUMN raw.sec_instrument_titles.document_hash IS
  'SHA-256 hash of the source filing XBRL instance';
COMMENT ON COLUMN raw.sec_instrument_titles.content_hash IS
  'SHA-256 hash of the CIK, ticker, title, accession, and source-document hash';
COMMENT ON COLUMN raw.sec_instrument_titles.retrieved_at IS
  'Timestamp when the filing instance was fetched and parsed';
