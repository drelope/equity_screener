"""Rebuild clean.ticker_profile from raw profile and reference data.

The raw profile table remains unchanged. This rebuild consolidates to one row
per normalized (CIK, ticker), selects a representative reference security using
active status and classifier evidence, keeps only consensus profile values,
and records every contributing raw profile for audit. ``source_profiles`` holds
lineage only (security, provider, retrieval time, payload hash and the loader
that set each column); the payload itself stays in raw.ticker_profile /
raw.ticker_profile_load and is joined on demand. Only groups with an active
representative are emitted, so deactivated tickers do not appear in the
curated snapshot while their lineage stays in ``source_profiles``.
When profile preferences are wholly absent, the representative's mined contract
preference supplies the value, with its source document retained in lineage.

Usage:
    python -m scripts.populate_clean_ticker_profile
"""

import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine

REBUILD_SQL = """
WITH candidates AS (
    SELECT LPAD(BTRIM(s.cik), 10, '0') AS cik,
           UPPER(BTRIM(s.ticker)) AS ticker,
           s.issuer_id,
           s.security_id,
           s.security_name,
           s.security_type,
           s.classify_source,
           s.classify_confidence,
           s.active,
           s.dividend,
           s.updated_at AS reference_updated_at,
           i.issuer_name,
           p.provider,
           NULLIF(BTRIM(p.sector), '') AS sector,
           NULLIF(BTRIM(p.industry), '') AS industry,
           NULLIF(BTRIM(p.security_type), '') AS profile_security_type,
           NULLIF(BTRIM(p.coupon_type), '') AS coupon_type,
           p.coupon_rate,
           p.fixed_period_end,
           p.floating_spread,
           NULLIF(BTRIM(p.tax_status), '') AS tax_status,
           p.call_date,
           p.liquidation_preference,
           ct.liquidation_preference AS contract_liquidation_preference,
           ct.first_call_date AS contract_first_call_date,
           ct.fixed_period_end AS contract_fixed_period_end,
           ct.floating_spread AS contract_floating_spread,
           ct.source_document_id AS contract_source_document_id,
           p.retrieved_at,
           MD5(p.raw_payload::text) AS payload_hash,
           p.field_sources,
           s.classification_evidence,
           (CASE WHEN s.active THEN 1000 ELSE 0 END)
           + (CASE LOWER(s.classify_confidence)
                  WHEN 'high' THEN 300
                  WHEN 'medium' THEN 200
                  WHEN 'low' THEN 100
                  ELSE 0
              END)
           + (CASE LOWER(s.classify_source)
                  WHEN 'dei_title' THEN 80
                  WHEN 'symbol_suffix' THEN 80
                  WHEN 'submissions_leading' THEN 70
                  WHEN 'issuer_title' THEN 60
                  WHEN 'dividend_facts' THEN 50
                  WHEN 'concept_bag' THEN 20
                  WHEN 'unavailable' THEN 10
                  ELSE 0
              END) AS evidence_rank
    FROM raw.ticker_profile AS p
    JOIN reference.securities AS s ON s.security_id = p.security_id
    LEFT JOIN reference.issuers AS i ON i.issuer_id = s.issuer_id
    LEFT JOIN preferred.contract_terms AS ct ON ct.security_id = s.security_id
    WHERE NULLIF(BTRIM(s.cik), '') IS NOT NULL
      AND NULLIF(BTRIM(s.ticker), '') IS NOT NULL
), ranked AS (
    SELECT candidates.*,
           ROW_NUMBER() OVER (
               PARTITION BY cik, ticker
               ORDER BY evidence_rank DESC,
                        reference_updated_at DESC NULLS LAST,
                        security_id
           ) AS representative_rank,
           MAX(evidence_rank) OVER (PARTITION BY cik, ticker) AS best_evidence_rank
    FROM candidates
), representatives AS (
    SELECT *
    FROM ranked
    WHERE representative_rank = 1
), resolved_candidates AS (
    SELECT ranked.*,
           representatives.security_type AS selected_security_type
    FROM ranked
    JOIN representatives USING (cik, ticker)
), grouped AS (
    SELECT cik,
           ticker,
           COUNT(*) AS profile_count,
           ARRAY_AGG(DISTINCT security_id ORDER BY security_id) AS source_security_ids,
           ARRAY_AGG(DISTINCT provider ORDER BY provider) AS provider_sources,
           COUNT(DISTINCT security_type) AS security_type_count,
           COUNT(DISTINCT security_type) FILTER (
               WHERE evidence_rank = best_evidence_rank
           ) AS best_security_type_count,
           COUNT(DISTINCT sector) AS sector_count,
           COUNT(DISTINCT industry) AS industry_count,
           COUNT(DISTINCT profile_security_type) FILTER (
               WHERE security_type = selected_security_type
           ) AS profile_security_type_count,
           COUNT(DISTINCT coupon_type) FILTER (
               WHERE security_type = selected_security_type
           ) AS coupon_type_count,
           COUNT(DISTINCT coupon_rate) FILTER (
               WHERE security_type = selected_security_type
           ) AS coupon_rate_count,
           COUNT(DISTINCT fixed_period_end) FILTER (
               WHERE security_type = selected_security_type
           ) AS fixed_period_end_count,
           COUNT(DISTINCT floating_spread) FILTER (
               WHERE security_type = selected_security_type
           ) AS floating_spread_count,
           COUNT(DISTINCT tax_status) FILTER (
               WHERE security_type = selected_security_type
           ) AS tax_status_count,
           COUNT(DISTINCT call_date) FILTER (
               WHERE security_type = selected_security_type
           ) AS call_date_count,
           COUNT(DISTINCT liquidation_preference) FILTER (
               WHERE security_type = selected_security_type
           ) AS liquidation_preference_count,
           CASE WHEN COUNT(DISTINCT sector) <= 1 THEN MAX(sector) END AS sector,
           CASE WHEN COUNT(DISTINCT industry) <= 1 THEN MAX(industry) END AS industry,
           CASE WHEN COUNT(DISTINCT profile_security_type) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(profile_security_type) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS profile_security_type,
           CASE WHEN COUNT(DISTINCT coupon_type) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(coupon_type) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS coupon_type,
           CASE WHEN COUNT(DISTINCT coupon_rate) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(coupon_rate) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS coupon_rate,
           CASE WHEN COUNT(DISTINCT fixed_period_end) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(fixed_period_end) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS fixed_period_end,
           CASE WHEN COUNT(DISTINCT floating_spread) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(floating_spread) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS floating_spread,
           CASE WHEN COUNT(DISTINCT tax_status) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(tax_status) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS tax_status,
           CASE WHEN COUNT(DISTINCT call_date) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(call_date) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS call_date,
           CASE WHEN COUNT(DISTINCT liquidation_preference) FILTER (
                    WHERE security_type = selected_security_type
                ) <= 1
                THEN MAX(liquidation_preference) FILTER (
                    WHERE security_type = selected_security_type
                ) END AS liquidation_preference,
           JSONB_AGG(
               JSONB_BUILD_OBJECT(
                   'security_id', security_id,
                   'provider', provider,
                   'retrieved_at', retrieved_at,
                   'payload_hash', payload_hash,
                   'field_sources', field_sources,
                   'security_type', security_type,
                   'classify_source', classify_source,
                   'classify_confidence', classify_confidence,
                   'classification_evidence', classification_evidence,
                   'contract_liquidation_preference', contract_liquidation_preference,
                   'contract_first_call_date', contract_first_call_date,
                   'contract_fixed_period_end', contract_fixed_period_end,
                   'contract_floating_spread', contract_floating_spread,
                   'contract_source_document_id', contract_source_document_id
               )
               ORDER BY security_id, provider
           ) AS source_profiles,
           JSONB_STRIP_NULLS(JSONB_BUILD_OBJECT(
               'security_type_candidates', CASE WHEN COUNT(DISTINCT security_type) > 1
                   THEN TO_JSONB(ARRAY_AGG(DISTINCT security_type ORDER BY security_type)) END,
               'security_type', CASE WHEN COUNT(DISTINCT security_type) FILTER (
                   WHERE evidence_rank = best_evidence_rank
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT security_type ORDER BY security_type
                   ) FILTER (WHERE evidence_rank = best_evidence_rank)) END,
               'sector', CASE WHEN COUNT(DISTINCT sector) > 1
                   THEN TO_JSONB(ARRAY_AGG(DISTINCT sector ORDER BY sector)) END,
               'industry', CASE WHEN COUNT(DISTINCT industry) > 1
                   THEN TO_JSONB(ARRAY_AGG(DISTINCT industry ORDER BY industry)) END,
               'profile_security_type', CASE WHEN COUNT(DISTINCT profile_security_type) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT profile_security_type ORDER BY profile_security_type
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'coupon_type', CASE WHEN COUNT(DISTINCT coupon_type) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT coupon_type ORDER BY coupon_type
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'coupon_rate', CASE WHEN COUNT(DISTINCT coupon_rate) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT coupon_rate ORDER BY coupon_rate
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'fixed_period_end', CASE WHEN COUNT(DISTINCT fixed_period_end) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT fixed_period_end ORDER BY fixed_period_end
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'floating_spread', CASE WHEN COUNT(DISTINCT floating_spread) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT floating_spread ORDER BY floating_spread
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'tax_status', CASE WHEN COUNT(DISTINCT tax_status) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT tax_status ORDER BY tax_status
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'call_date', CASE WHEN COUNT(DISTINCT call_date) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT call_date ORDER BY call_date
                   ) FILTER (WHERE security_type = selected_security_type)) END,
               'liquidation_preference', CASE WHEN COUNT(DISTINCT liquidation_preference) FILTER (
                   WHERE security_type = selected_security_type
               ) > 1
                   THEN TO_JSONB(ARRAY_AGG(
                       DISTINCT liquidation_preference ORDER BY liquidation_preference
                   ) FILTER (WHERE security_type = selected_security_type)) END
           )) AS metadata_conflicts
    FROM resolved_candidates
    GROUP BY cik, ticker
)
INSERT INTO clean.ticker_profile (
    cik, ticker, issuer_id, security_id, source_security_ids, profile_count,
    provider_sources, issuer_name, security_name, security_type,
    classify_source, classify_confidence, profile_security_type, active,
    dividend, classification_conflict, sector, industry, coupon_type,
    coupon_rate, fixed_period_end, floating_spread, tax_status, call_date,
    liquidation_preference, liquidation_preference_conflict,
    metadata_conflicts, source_profiles, cleaned_at
)
SELECT representative.cik,
       representative.ticker,
       representative.issuer_id,
       representative.security_id,
       grouped.source_security_ids,
       grouped.profile_count,
       grouped.provider_sources,
       representative.issuer_name,
       representative.security_name,
       representative.security_type,
       representative.classify_source,
       representative.classify_confidence,
       grouped.profile_security_type,
       representative.active,
       representative.dividend,
    grouped.best_security_type_count > 1,
       grouped.sector,
       grouped.industry,
       grouped.coupon_type,
       grouped.coupon_rate,
       CASE WHEN grouped.fixed_period_end_count = 0
                 AND representative.security_type = 'preferred stock'
            THEN representative.contract_fixed_period_end
            ELSE grouped.fixed_period_end END,
       CASE WHEN grouped.floating_spread_count = 0
                 AND representative.security_type = 'preferred stock'
            THEN representative.contract_floating_spread
            ELSE grouped.floating_spread END,
       grouped.tax_status,
       CASE WHEN grouped.call_date_count = 0
                 AND representative.security_type = 'preferred stock'
            THEN representative.contract_first_call_date
            ELSE grouped.call_date END,
       CASE WHEN grouped.liquidation_preference_count = 0
                 AND representative.security_type = 'preferred stock'
            THEN representative.contract_liquidation_preference
            ELSE grouped.liquidation_preference END,
       grouped.liquidation_preference_count > 1,
       grouped.metadata_conflicts,
       grouped.source_profiles,
       now()
FROM grouped
JOIN representatives AS representative
  USING (cik, ticker)
WHERE representative.active = TRUE;
"""


def rebuild_clean_ticker_profile():
    """Replace the curated snapshot atomically from the current source tables."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM clean.ticker_profile"))
        result = conn.execute(text(REBUILD_SQL))
    return result.rowcount


def main():
    row_count = rebuild_clean_ticker_profile()
    print(f"Rebuilt clean.ticker_profile: {row_count} normalized instruments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
