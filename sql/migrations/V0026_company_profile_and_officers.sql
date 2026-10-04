-- =====================================================================
-- V0026 company_profile_and_officers
-- Store scalar company-profile fields separately from normalized officer
-- child rows. Source epoch values are converted by the clean-profile loader.
-- =====================================================================

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

DO $comments$
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
      WHEN 'source_payload' THEN 'JSONB snapshot of the selected scalar source profile fields; officer arrays are stored separately'
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
$comments$;