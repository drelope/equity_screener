-- =====================================================================
-- V0025 clean_ticker_profile
-- Curated one-row-per-CIK-and-ticker view of provider profile data. The raw
-- table remains untouched; scripts.populate_clean_ticker_profile rebuilds
-- this table after profile-producing ETL stages complete.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS clean;

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
  'TRUE when contributing reference rows disagree on canonical security_type';
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