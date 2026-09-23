-- =====================================================================
-- V0003 comments_manifest
-- Missing COMMENT ON COLUMN statements for sql/schema.sql (187 columns).
-- Generated from PostgreSqlDdlCommentScript_MissingComments.md (companion spec).
-- Wrapped in a single DO block so scripts/migrate.py can apply the file as
-- one statement. Idempotent: COMMENT ON simply overwrites prior comments.
--
-- The block self-converges the pre-V0004 naming (reference.issuers.legal_name
-- and the denormalized reference.securities.issuer_name) before commenting:
-- fresh installs running schema.sql create the canonical names directly, while
-- databases created before V0004 still carry the legacy columns, and migrate.py
-- applies this file before V0004. Guarding the rename/drop here keeps the
-- manifest applicable to both states.
-- =====================================================================

DO $comments$
BEGIN

-- Converge legacy column names so the manifest applies on pre-V0004 schemas.
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'issuers'
      AND column_name = 'legal_name'
) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'issuers'
      AND column_name = 'issuer_name'
) THEN
    ALTER TABLE reference.issuers RENAME COLUMN legal_name TO issuer_name;
END IF;

IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'reference' AND table_name = 'securities'
      AND column_name = 'issuer_name'
) THEN
    ALTER TABLE reference.securities DROP COLUMN issuer_name;
END IF;

-- Missing column comments for: raw.company_ticker
COMMENT ON COLUMN raw.company_ticker.ticker IS
  'dei:TradingSymbol; SEC-listed ticker symbol (e.g. ACR, ACR-PC, GOOGL); primary key for one listed series';
COMMENT ON COLUMN raw.company_ticker.cik IS
  'SEC Central Index Key, zero-padded to 10 characters; links to reference.securities and the CIK-keyed issuer payload tables';
COMMENT ON COLUMN raw.company_ticker.title IS
  'Registrant name as reported in SEC company_tickers.json (dei:EntityRegistrantName)';
COMMENT ON COLUMN raw.company_ticker.source_url IS
  'URL of the SEC company_tickers.json source this row was loaded from; provenance metadata, not an XBRL fact';
COMMENT ON COLUMN raw.company_ticker.raw_payload IS
  'Unmodified JSON object from SEC company_tickers.json; retained for audit and re-processing, not an XBRL fact';
COMMENT ON COLUMN raw.company_ticker.retrieved_at IS
  'Timestamp (UTC) when the SEC company_tickers.json snapshot was fetched';

-- Missing column comments for: raw.market_data
COMMENT ON COLUMN raw.market_data.security_id IS
  'References reference.securities (security_id); the listed security these OHLCV bars belong to';
COMMENT ON COLUMN raw.market_data.observation_date IS
  'Trading date of the OHLCV bar on the provider calendar';
COMMENT ON COLUMN raw.market_data.open IS
  'Daily opening price in the provider currency (USD)';
COMMENT ON COLUMN raw.market_data.high IS
  'Daily highest traded price in the provider currency (USD)';
COMMENT ON COLUMN raw.market_data.low IS
  'Daily lowest traded price in the provider currency (USD)';
COMMENT ON COLUMN raw.market_data.close IS
  'Daily closing price in the provider currency (USD)';
COMMENT ON COLUMN raw.market_data.adjusted_close IS
  'Split- and dividend-adjusted closing price used for return calculations; provider data, not an XBRL fact';
COMMENT ON COLUMN raw.market_data.volume IS
  'Number of shares traded on the observation date';
COMMENT ON COLUMN raw.market_data.provider IS
  'Market data provider that supplied the bar (e.g. OPENBB, YFINANCE); not an XBRL fact';
COMMENT ON COLUMN raw.market_data.retrieved_at IS
  'Timestamp (UTC) when the market data row was fetched from the provider';

-- Missing column comments for: raw.ticker_profile
COMMENT ON COLUMN raw.ticker_profile.security_id IS
  'References reference.securities (security_id); one profile summary per listed security';
COMMENT ON COLUMN raw.ticker_profile.ticker IS
  'Ticker symbol the profile was fetched under (e.g. ACR-PD)';
COMMENT ON COLUMN raw.ticker_profile.provider IS
  'Profile provider (OPENBB_YFINANCE by default; SEC_XBRL+OPENBB_YFINANCE when XBRL tags were merged); not an XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.security_type IS
  'Security classification reported by the profile provider (e.g. Series C Preferred Stock); not an XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.raw_payload IS
  'Full profile JSON from the provider(s), including the sec_xbrl section; kept for audit, not an XBRL fact';
COMMENT ON COLUMN raw.ticker_profile.retrieved_at IS
  'Timestamp (UTC) when the profile summary was fetched';

-- Missing column comments for: raw.dividend_data
COMMENT ON COLUMN raw.dividend_data.security_id IS
  'References reference.securities (security_id); the security this dividend record belongs to';
COMMENT ON COLUMN raw.dividend_data.adjusted_amount IS
  'Per-share dividend amount adjusted for share splits, in the record currency (USD)';
COMMENT ON COLUMN raw.dividend_data.provider IS
  'Dividend data provider (SEC_XBRL or OPENBB); not an XBRL fact';
COMMENT ON COLUMN raw.dividend_data.retrieved_at IS
  'Timestamp (UTC) when the dividend record was loaded';

-- Missing column comments for: raw.companyfacts
COMMENT ON COLUMN raw.companyfacts.cik IS
  'SEC Central Index Key, zero-padded to 10 characters; primary key; one issuer-level companyfacts payload per CIK';
COMMENT ON COLUMN raw.companyfacts.company_name IS
  'Registrant name as reported in the companyfacts payload (dei:EntityRegistrantName)';
COMMENT ON COLUMN raw.companyfacts.concept_groups IS
  'Grouped concept names (dividends, earnings, cash_flow, balance_sheet, ...) extracted from the payload; JSONB index for downstream screens, not an XBRL fact';
COMMENT ON COLUMN raw.companyfacts.raw_payload IS
  'Unmodified companyfacts JSON from data.sec.gov/api/xbrl/companyfacts (lz4-compressed); not an XBRL fact';
COMMENT ON COLUMN raw.companyfacts.content_hash IS
  'SHA-256 hash of the payload; used to skip unchanged re-downloads and detect drift, not an XBRL fact';
COMMENT ON COLUMN raw.companyfacts.provider IS
  'Payload source tag, SEC_XBRL by default; not an XBRL fact';
COMMENT ON COLUMN raw.companyfacts.retrieved_at IS
  'Timestamp (UTC) when the payload was fetched from SEC';

-- Missing column comments for: raw.company_taxonomy
COMMENT ON COLUMN raw.company_taxonomy.cik IS
  'SEC Central Index Key, zero-padded to 10 characters; primary key; one taxonomy-scoped concept payload per CIK';
COMMENT ON COLUMN raw.company_taxonomy.company_name IS
  'Registrant name as reported in the companyconcept response (dei:EntityRegistrantName)';
COMMENT ON COLUMN raw.company_taxonomy.taxonomies IS
  'Per-taxonomy concept lists (us-gaap, dei) returned by the XBRL Data API companyconcept endpoint';
COMMENT ON COLUMN raw.company_taxonomy.concept_groups IS
  'Grouped preferred-stock concept names subset; JSONB index, not an XBRL fact';
COMMENT ON COLUMN raw.company_taxonomy.raw_payload IS
  'Unmodified companyconcept JSON payloads, kept per CIK; not an XBRL fact';
COMMENT ON COLUMN raw.company_taxonomy.content_hash IS
  'SHA-256 hash of the payload for change detection; not an XBRL fact';
COMMENT ON COLUMN raw.company_taxonomy.provider IS
  'Payload source tag, SEC_XBRL by default; not an XBRL fact';
COMMENT ON COLUMN raw.company_taxonomy.retrieved_at IS
  'Timestamp (UTC) when the taxonomy payload was fetched from SEC';

-- Missing column comments for: raw.sec_submissions
COMMENT ON COLUMN raw.sec_submissions.cik IS
  'SEC Central Index Key, zero-padded to 10 characters; primary key; one submissions history per CIK';
COMMENT ON COLUMN raw.sec_submissions.company_name IS
  'Registrant name from the submissions payload (dei:EntityRegistrantName)';
COMMENT ON COLUMN raw.sec_submissions.raw_payload IS
  'Unmodified submissions JSON from data.sec.gov/submissions (lz4-compressed); not an XBRL fact';
COMMENT ON COLUMN raw.sec_submissions.content_hash IS
  'SHA-256 hash of the payload for change detection; not an XBRL fact';
COMMENT ON COLUMN raw.sec_submissions.provider IS
  'Payload source tag, SEC_SUBMISSIONS by default; not an XBRL fact';
COMMENT ON COLUMN raw.sec_submissions.retrieved_at IS
  'Timestamp (UTC) when the submissions payload was fetched from SEC';

-- Missing column comments for: raw.company_classification
COMMENT ON COLUMN raw.company_classification.cik IS
  'SEC Central Index Key, zero-padded to 10 characters; primary key; classification cache keyed once per issuer';
COMMENT ON COLUMN raw.company_classification.ticker IS
  'SEC ticker used by stage 0 to identify the issuer';
COMMENT ON COLUMN raw.company_classification.company_name IS
  'Registrant name (dei:EntityRegistrantName) extracted during classification';
COMMENT ON COLUMN raw.company_classification.security_types IS
  'JSONB array of normalized security classes detected by classify_companyfacts() (e.g. common_stock, preferred stock)';
COMMENT ON COLUMN raw.company_classification.security_facts IS
  'JSONB array of security-classification XBRL concept names found in the payload';
COMMENT ON COLUMN raw.company_classification.dividend_facts IS
  'JSONB array of dividend-related XBRL concept names found in the payload';
COMMENT ON COLUMN raw.company_classification.dividend IS
  'TRUE when positive dividend or owner-distribution (us-gaap) evidence was found; drives the dividend-universe gating';
COMMENT ON COLUMN raw.company_classification.status IS
  'Classification availability: available | unavailable';
COMMENT ON COLUMN raw.company_classification.content_hash IS
  'SHA-256 hash of the source companyfacts payload that built this cache row; not an XBRL fact';
COMMENT ON COLUMN raw.company_classification.retrieved_at IS
  'Timestamp (UTC) when the classification was computed';

-- Missing column comments for: raw.sec_documents
COMMENT ON COLUMN raw.sec_documents.document_id IS
  'Surrogate primary key for one indexed filing document';
COMMENT ON COLUMN raw.sec_documents.security_id IS
  'References reference.securities (security_id); NULL for filings not tied to a listed security; unique partial index keeps one row per security';
COMMENT ON COLUMN raw.sec_documents.cik IS
  'Issuer CIK the filing belongs to';
COMMENT ON COLUMN raw.sec_documents.accession_no IS
  'SEC accession number of the filing (e.g. 0000320193-23-000106)';
COMMENT ON COLUMN raw.sec_documents.form_type IS
  'SEC form type of the filing (10-K, 10-Q, 8-K, ...)';
COMMENT ON COLUMN raw.sec_documents.filing_date IS
  'Date the filing was submitted to SEC (filed)';
COMMENT ON COLUMN raw.sec_documents.report_date IS
  'Reporting period end date covered by the document';
COMMENT ON COLUMN raw.sec_documents.primary_document IS
  'Name of the primary document (e.g. index.htm or the full-submission file)';
COMMENT ON COLUMN raw.sec_documents.source_url IS
  'SEC EDGAR URL the document was downloaded from';
COMMENT ON COLUMN raw.sec_documents.concept_groups IS
  'Per-security XBRL concept groups extracted from the stored document; refreshed by populate_sec_documents without new SEC requests';
COMMENT ON COLUMN raw.sec_documents.retrieved_at IS
  'Timestamp (UTC) when the document was fetched or refreshed';
COMMENT ON COLUMN raw.sec_documents.content_hash IS
  'SHA-256 hash of the extracted concept groups; identical across series of one issuer is legitimate, so it is indexed but not unique';
COMMENT ON COLUMN raw.sec_documents.raw_text IS
  'Full extracted text of the filing used for iXBRL narrative parsing';

-- Missing column comments for: reference.exchanges
COMMENT ON COLUMN reference.exchanges.exchange_id IS
  'Surrogate primary key for one exchange (e.g. 1 = NYSE, 2 = NASDAQ)';
COMMENT ON COLUMN reference.exchanges.exchange_code IS
  'Exchange code (e.g. NYSE, NASDAQ); unique and NOT NULL';
COMMENT ON COLUMN reference.exchanges.exchange_name IS
  'Human-readable exchange name';

-- Missing column comments for: reference.issuers
COMMENT ON COLUMN reference.issuers.issuer_id IS
  'Surrogate primary key for one SEC issuer; referenced by reference.securities.issuer_id';
COMMENT ON COLUMN reference.issuers.cik IS
  'SEC Central Index Key of the issuer; unique';
COMMENT ON COLUMN reference.issuers.issuer_name IS
  'Registrant name (dei:EntityRegistrantName); the canonical issuer name, '
  'referenced by every listed security through reference.securities.issuer_id';
COMMENT ON COLUMN reference.issuers.sic IS
  'SEC Standard Industrial Classification code of the issuer';
COMMENT ON COLUMN reference.issuers.fiscal_year_end IS
  'Month/day string of the issuer fiscal year end (e.g. 12-31)';

-- Missing column comments for: reference.securities
COMMENT ON COLUMN reference.securities.active IS
  'TRUE when the security is currently listed and tracked; FALSE for delisted or retired rows. The dividend-universe gate requires dividend = TRUE AND active = TRUE';

-- Missing column comments for: preferred.security_terms
COMMENT ON COLUMN preferred.security_terms.security_id IS
  'References reference.securities (security_id); one terms row per preferred security';
COMMENT ON COLUMN preferred.security_terms.source_document_id IS
  'References raw.sec_documents (document_id); supporting filing the terms were extracted from';
COMMENT ON COLUMN preferred.security_terms.confidence_score IS
  'Confidence (0-1) that the extracted terms are correct; NULL when unverified';
COMMENT ON COLUMN preferred.security_terms.reviewed_by IS
  'User or process that manually reviewed and approved the terms';
COMMENT ON COLUMN preferred.security_terms.reviewed_at IS
  'Timestamp (UTC) when the terms row was last reviewed';

-- Missing column comments for: preferred.dividend_snapshot
COMMENT ON COLUMN preferred.dividend_snapshot.security_id IS
  'References reference.securities (security_id); one snapshot row per preferred security';
COMMENT ON COLUMN preferred.dividend_snapshot.ticker IS
  'Ticker symbol of the preferred security (e.g. ACR-PC)';
COMMENT ON COLUMN preferred.dividend_snapshot.cik IS
  'Issuer CIK the dividend evidence was read from';
COMMENT ON COLUMN preferred.dividend_snapshot.preferred_flag IS
  'TRUE when the security was classified as a preferred series';
COMMENT ON COLUMN preferred.dividend_snapshot.latest_dividend_period_end IS
  'Period end date (xbrl:periodEnd) of the most recent dividend fact';
COMMENT ON COLUMN preferred.dividend_snapshot.latest_dividend_filed IS
  'Filing date of the most recent dividend fact (xbrl:periodEnd fact filed)';
COMMENT ON COLUMN preferred.dividend_snapshot.latest_dividend_form IS
  'SEC form (10-K, 10-Q, 8-K) of the filing that supplied the latest dividend fact';
COMMENT ON COLUMN preferred.dividend_snapshot.retrieved_at IS
  'Timestamp (UTC) when the snapshot was built';

-- Missing column comments for: fundamentals.periodic_financials
COMMENT ON COLUMN fundamentals.periodic_financials.security_id IS
  'References reference.securities (security_id); the security this financial statement row belongs to';
COMMENT ON COLUMN fundamentals.periodic_financials.period_end IS
  'End date of the reporting period (xbrl:periodEnd)';
COMMENT ON COLUMN fundamentals.periodic_financials.fiscal_year IS
  'Fiscal year of the reporting period (fact fy)';
COMMENT ON COLUMN fundamentals.periodic_financials.fiscal_period IS
  'Fiscal period of the report: Q1 | Q2 | Q3 | FY';
COMMENT ON COLUMN fundamentals.periodic_financials.revenue IS
  'Total revenues for the period, in USD (us-gaap:Revenues)';
COMMENT ON COLUMN fundamentals.periodic_financials.operating_income IS
  'Operating income for the period, in USD (us-gaap:OperatingIncomeLoss)';
COMMENT ON COLUMN fundamentals.periodic_financials.net_income IS
  'Net income attributable to the entity, in USD (us-gaap:NetIncomeLoss)';
COMMENT ON COLUMN fundamentals.periodic_financials.eps IS
  'Earnings per share for the period, in USD per share (us-gaap:EarningsPerShareBasicAndDiluted)';
COMMENT ON COLUMN fundamentals.periodic_financials.cash IS
  'Cash and cash equivalents at period end, in USD (us-gaap:CashAndCashEquivalentsAtCarryingValue)';
COMMENT ON COLUMN fundamentals.periodic_financials.assets IS
  'Total assets at period end, in USD (us-gaap:Assets)';
COMMENT ON COLUMN fundamentals.periodic_financials.liabilities IS
  'Total liabilities at period end, in USD (us-gaap:Liabilities)';
COMMENT ON COLUMN fundamentals.periodic_financials.debt IS
  'Total debt at period end, in USD (us-gaap:LongTermDebt and us-gaap:ShortTermBorrowings)';
COMMENT ON COLUMN fundamentals.periodic_financials.equity IS
  'Total stockholders equity at period end, in USD (us-gaap:StockholdersEquity)';
COMMENT ON COLUMN fundamentals.periodic_financials.operating_cash_flow IS
  'Net cash from operating activities for the period, in USD (us-gaap:NetCashProvidedByUsedInOperatingActivities)';
COMMENT ON COLUMN fundamentals.periodic_financials.capital_expenditures IS
  'Capital expenditures for the period, in USD (us-gaap:PaymentsToAcquirePropertyPlantAndEquipment)';
COMMENT ON COLUMN fundamentals.periodic_financials.free_cash_flow IS
  'Free cash flow for the period, in USD (operating cash flow minus capital expenditures)';
COMMENT ON COLUMN fundamentals.periodic_financials.source IS
  'Source of the financials (e.g. SEC XBRL); not an XBRL fact';
COMMENT ON COLUMN fundamentals.periodic_financials.retrieved_at IS
  'Timestamp (UTC) when the financials row was loaded';

-- Missing column comments for: model.features
COMMENT ON COLUMN model.features.security_id IS
  'References reference.securities (security_id); feature row per security';
COMMENT ON COLUMN model.features.as_of_date IS
  'Feature observation date; one feature row per security per trading day';
COMMENT ON COLUMN model.features.current_price IS
  'Latest close price as of as_of_date, in USD per share';
COMMENT ON COLUMN model.features.annualized_dividend IS
  'Trailing 12-month sum of per-share dividends, in USD per share';
COMMENT ON COLUMN model.features.dividend_yield IS
  'Annualized dividend divided by current price; decimal fraction (e.g. 0.05 = 5%)';
COMMENT ON COLUMN model.features.dividend_growth IS
  'Year-over-year growth rate of the annualized dividend; decimal fraction; NULL until populated';
COMMENT ON COLUMN model.features.earnings_payout IS
  'Dividend per share divided by earnings per share; decimal fraction; NULL until populated';
COMMENT ON COLUMN model.features.fcf_payout IS
  'Dividends paid divided by free cash flow; decimal fraction; NULL until populated';
COMMENT ON COLUMN model.features.dividend_coverage IS
  'Free cash flow divided by dividends paid; decimal fraction; NULL until populated';
COMMENT ON COLUMN model.features.debt_to_ebitda IS
  'Total debt divided by EBITDA; decimal ratio; NULL until populated';
COMMENT ON COLUMN model.features.interest_coverage IS
  'Operating income divided by interest expense; decimal ratio; NULL until populated';
COMMENT ON COLUMN model.features.volatility_252d IS
  'Annualized standard deviation of daily log returns over the trailing 252 trading days';
COMMENT ON COLUMN model.features.momentum_252d IS
  'Relative price change over the trailing 252 trading days (close/close-252 minus 1); decimal fraction (e.g. 0.10 = 10%)';
COMMENT ON COLUMN model.features.momentum_63d IS
  'Relative price change over the trailing 63 trading days (close/close-63 minus 1); decimal fraction';
COMMENT ON COLUMN model.features.liquidation_discount IS
  'Discount of market price to the preferred liquidation preference; decimal fraction; NULL until populated';
COMMENT ON COLUMN model.features.legal_rights_score IS
  'Legal and protective-rights strength score on 0-1; NULL until populated';
COMMENT ON COLUMN model.features.data_quality_score IS
  'Data-quality score of the underlying sources on 0-1; NULL until populated';
COMMENT ON COLUMN model.features.target_sustainable_dividend IS
  'Binary label 0/1 indicating a sustainable dividend; starter code intentionally leaves it NULL rather than fabricating labels';

-- Missing column comments for: model.scores
COMMENT ON COLUMN model.scores.security_id IS
  'References reference.securities (security_id); score row per security';
COMMENT ON COLUMN model.scores.as_of_date IS
  'Scoring date of the row';
COMMENT ON COLUMN model.scores.dividend_income_score IS
  'Percentile rank (0-1) of dividend yield across the screened universe';
COMMENT ON COLUMN model.scores.sustainability_score IS
  'Weighted percentile (0-1) blending dividend_coverage (0.5), dividend_growth (0.2) and inverse fcf_payout (0.3)';
COMMENT ON COLUMN model.scores.legal_rights_score IS
  'Legal-rights score on 0-1; defaults to 0.5 when not derivable';
COMMENT ON COLUMN model.scores.appreciation_score IS
  'Percentile (0-1) combining momentum_252d (0.6) and momentum_63d (0.4)';
COMMENT ON COLUMN model.scores.risk_score IS
  'Inverse percentile (0-1) of volatility_252d; higher value means lower risk';
COMMENT ON COLUMN model.scores.valuation_score IS
  'Valuation percentile (0-1); constant 0.5 in the rule-based scorer';
COMMENT ON COLUMN model.scores.composite_score IS
  'Weighted blend (0-1) of the six sub-scores; WEIGHTS defined in src/crispdm/scoring.py';

-- Missing column comments for: model.predictions
COMMENT ON COLUMN model.predictions.run_id IS
  'UUID of the model run; shared by every prediction row of one campaign (immutable run)';
COMMENT ON COLUMN model.predictions.security_id IS
  'References reference.securities (security_id); predicted security';
COMMENT ON COLUMN model.predictions.as_of_date IS
  'Prediction date';
COMMENT ON COLUMN model.predictions.probability IS
  'Predicted probability of a sustainable dividend; composite_score clipped to 0-1';
COMMENT ON COLUMN model.predictions.predicted_class IS
  'Binary classification: 1 when composite_score >= precision_threshold, else 0';
COMMENT ON COLUMN model.predictions.precision_threshold IS
  'Decision threshold used for predicted_class (default 0.5)';
COMMENT ON COLUMN model.predictions.model_version IS
  'Version identifier of the model (e.g. rule_scoring_v1)';
COMMENT ON COLUMN model.predictions.feature_version IS
  'Version identifier of the feature set (e.g. features_v1)';
COMMENT ON COLUMN model.predictions.data_version IS
  'Version identifier of the input data (e.g. sec_xbrl_v1)';
COMMENT ON COLUMN model.predictions.created_at IS
  'Timestamp (UTC) when the prediction row was written';

-- Missing column comments for: model.rankings
COMMENT ON COLUMN model.rankings.security_id IS
  'References reference.securities (security_id); ranked security';
COMMENT ON COLUMN model.rankings.as_of_date IS
  'Ranking date';
COMMENT ON COLUMN model.rankings.rank IS
  'Rank of the security by composite_score within the as_of_date universe (1 = best)';
COMMENT ON COLUMN model.rankings.composite_score IS
  'Composite score (0-1) that determined the rank';
COMMENT ON COLUMN model.rankings.probability IS
  'Sustainable-dividend probability used for the ranking; composite_score clipped to 0-1';

-- Missing column comments for: audit.source_lineage
COMMENT ON COLUMN audit.source_lineage.lineage_id IS
  'Surrogate primary key for one provenance record';
COMMENT ON COLUMN audit.source_lineage.security_id IS
  'References reference.securities (security_id); security the sourced field belongs to';
COMMENT ON COLUMN audit.source_lineage.field_name IS
  'Name of the decision field whose provenance is recorded (e.g. security_type, coupon_rate, liquidation_preference, issuer_name, dividend)';
COMMENT ON COLUMN audit.source_lineage.field_value IS
  'Value of the field at provenance-capture time';
COMMENT ON COLUMN audit.source_lineage.source IS
  'Source table or process that supplied the value (e.g. raw.ticker_profile, reference.securities)';
COMMENT ON COLUMN audit.source_lineage.source_document IS
  'Document or table detail of the source';
COMMENT ON COLUMN audit.source_lineage.filing_date IS
  'Filing date of the source document, when applicable';
COMMENT ON COLUMN audit.source_lineage.period IS
  'Reporting period of the source, when applicable';
COMMENT ON COLUMN audit.source_lineage.retrieval_date IS
  'Timestamp (UTC) when the provenance record was written';
COMMENT ON COLUMN audit.source_lineage.provider IS
  'Provider of the sourced value (SEC_XBRL, YFINANCE, OPENBB, ...)';
COMMENT ON COLUMN audit.source_lineage.confidence_score IS
  'Confidence (0-1) that the sourced value is reliable; derived from provider reliability';

-- Missing column comments for: audit.data_quality
COMMENT ON COLUMN audit.data_quality.security_id IS
  'References reference.securities (security_id); quality snapshot per security';
COMMENT ON COLUMN audit.data_quality.as_of_date IS
  'Quality snapshot date';
COMMENT ON COLUMN audit.data_quality.source_reliability IS
  'Maximum reliability (0-1) of the sources backing the security data';
COMMENT ON COLUMN audit.data_quality.completeness IS
  'Completeness of the security data (0-1); 1.0 with a ticker profile, 0.5 with only companyfacts';
COMMENT ON COLUMN audit.data_quality.recency IS
  'Recency decay (0-1) of the most recent retrieval; 1.0 when fetched today, falling to 0 over one year';
COMMENT ON COLUMN audit.data_quality.consistency IS
  'Consistency (0-1) between raw.ticker_profile.security_type and reference.securities.security_type';
COMMENT ON COLUMN audit.data_quality.quality_score IS
  'Weighted blend (0-1) of reliability 0.4, completeness 0.3, recency 0.2 and consistency 0.1';
COMMENT ON COLUMN audit.data_quality.status IS
  'Quality band: no data | good | fair | poor (score >= 0.8 good, >= 0.5 fair, else poor)';

-- Missing column comments for: audit.model_runs
COMMENT ON COLUMN audit.model_runs.run_id IS
  'UUID primary key of one model run';
COMMENT ON COLUMN audit.model_runs.model_version IS
  'Model version identifier';
COMMENT ON COLUMN audit.model_runs.feature_version IS
  'Feature-set version identifier';
COMMENT ON COLUMN audit.model_runs.data_version IS
  'Training-data version identifier';
COMMENT ON COLUMN audit.model_runs.training_start IS
  'First date of the training window';
COMMENT ON COLUMN audit.model_runs.training_end IS
  'Last date of the training window';
COMMENT ON COLUMN audit.model_runs.test_start IS
  'First date of the held-out test window';
COMMENT ON COLUMN audit.model_runs.test_end IS
  'Last date of the held-out test window';
COMMENT ON COLUMN audit.model_runs.precision IS
  'Model precision on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.recall IS
  'Model recall on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.f1 IS
  'Model F1 score on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.pr_auc IS
  'Precision-recall AUC on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.roc_auc IS
  'ROC AUC on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.accuracy IS
  'Model accuracy on the test window, on 0-1';
COMMENT ON COLUMN audit.model_runs.parameters IS
  'JSONB of hyperparameters and run configuration; not an XBRL fact';
COMMENT ON COLUMN audit.model_runs.created_at IS
  'Timestamp (UTC) when the run was recorded';

END
$comments$;