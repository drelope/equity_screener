-- =====================================================================
-- V0028 foreign_key_indexes
-- Add child-side indexes for audited foreign keys, and remove one unused
-- duplicate of the actively used periodic-financials vintage index.
-- =====================================================================

CREATE INDEX IF NOT EXISTS ix_source_lineage_security_id
  ON audit.source_lineage (security_id);

CREATE INDEX IF NOT EXISTS ix_clean_company_profile_reference_security_id
  ON clean.company_profile (reference_security_id);
CREATE INDEX IF NOT EXISTS ix_clean_company_profile_source_profile_security_id
  ON clean.company_profile (source_profile_security_id);
CREATE INDEX IF NOT EXISTS ix_clean_ticker_profile_issuer_id
  ON clean.ticker_profile (issuer_id);
CREATE INDEX IF NOT EXISTS ix_clean_ticker_profile_security_id
  ON clean.ticker_profile (security_id);

CREATE INDEX IF NOT EXISTS ix_predictions_security_id
  ON model.predictions (security_id);

CREATE INDEX IF NOT EXISTS ix_contract_terms_source_document_id
  ON preferred.contract_terms (source_document_id);
CREATE INDEX IF NOT EXISTS ix_security_terms_source_document_id
  ON preferred.security_terms (source_document_id);

CREATE INDEX IF NOT EXISTS ix_securities_issuer_id
  ON reference.securities (issuer_id);
CREATE INDEX IF NOT EXISTS ix_securities_exchange_id
  ON reference.securities (exchange_id);
CREATE INDEX IF NOT EXISTS ix_securities_ticker_cik
  ON reference.securities (ticker, cik);

-- V0009 already created an identical, actively used index. This second index
-- came from the baseline schema and had zero scans while consuming 48 MB.
DROP INDEX IF EXISTS fundamentals.idx_periodic_financials_security_filed;