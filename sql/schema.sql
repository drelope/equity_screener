CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS fundamentals;
CREATE SCHEMA IF NOT EXISTS dividends;
CREATE SCHEMA IF NOT EXISTS preferred;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS model;
CREATE SCHEMA IF NOT EXISTS audit;

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
  'Whether SEC evidence indicates that the security pays a dividend';
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

COMMENT ON COLUMN preferred.security_terms.dividend_rate IS
  'Preferred dividend rate (percent/amount). XBRL: us-gaap:PreferredStockDividendRatePercentage '
  '(seeded from the latest raw.dividend_data amount when no XBRL rate was filed)';
COMMENT ON COLUMN preferred.security_terms.liquidation_preference IS
  'XBRL: us-gaap:PreferredStockLiquidationPreferenceValue / PreferredStockLiquidationPreference / '
  'TemporaryEquityLiquidationPreference(Value); fallback PreferredStockParOrStatedValuePerShare';
COMMENT ON COLUMN preferred.security_terms.preferred_series IS
  'Series label parsed from dei:SecurityTitle (e.g. "Series C Preferred Stock")';

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

CREATE TABLE IF NOT EXISTS fundamentals.periodic_financials (
  security_id UUID REFERENCES reference.securities(security_id),
  period_end DATE NOT NULL, fiscal_year INT, fiscal_period VARCHAR(16),
  revenue NUMERIC, operating_income NUMERIC, net_income NUMERIC, eps NUMERIC,
  cash NUMERIC, assets NUMERIC, liabilities NUMERIC, debt NUMERIC, equity NUMERIC,
  operating_cash_flow NUMERIC, capital_expenditures NUMERIC, free_cash_flow NUMERIC,
  source VARCHAR(64), retrieved_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(security_id, period_end, fiscal_period)
);

CREATE TABLE IF NOT EXISTS model.features (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, current_price NUMERIC, annualized_dividend NUMERIC,
  dividend_yield NUMERIC, dividend_growth NUMERIC, earnings_payout NUMERIC,
  fcf_payout NUMERIC, dividend_coverage NUMERIC, debt_to_ebitda NUMERIC,
  interest_coverage NUMERIC, volatility_252d NUMERIC, momentum_252d NUMERIC,
  momentum_63d NUMERIC, liquidation_discount NUMERIC, legal_rights_score NUMERIC,
  data_quality_score NUMERIC, target_sustainable_dividend INT,
  PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS model.scores (
  security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, dividend_income_score NUMERIC,
  sustainability_score NUMERIC, legal_rights_score NUMERIC,
  appreciation_score NUMERIC, risk_score NUMERIC, valuation_score NUMERIC,
  composite_score NUMERIC, PRIMARY KEY(security_id, as_of_date)
);

CREATE TABLE IF NOT EXISTS model.predictions (
  run_id UUID NOT NULL, security_id UUID REFERENCES reference.securities(security_id),
  as_of_date DATE NOT NULL, probability NUMERIC, predicted_class INT,
  precision_threshold NUMERIC, model_version VARCHAR(64),
  feature_version VARCHAR(64), data_version VARCHAR(64),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(run_id, security_id, as_of_date)
);

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
