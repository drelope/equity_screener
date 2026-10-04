-- V0032 issuer_terms
--
-- Expose the SEC XBRL preferred terms that
-- scripts.populate_preferred_profiles.py extracts per CIK and parks in
-- raw.ticker_profile.raw_payload->sec_xbrl, so the evidence is queryable
-- without promoting it into the per-series columns of clean.ticker_profile.
--
-- Why a view and not new columns on clean.ticker_profile:
--
--   SEC Company Facts are filed per issuer and carry no member/series
--   dimension, so a coupon rate or liquidation amount read from them
--   describes the whole issuer. scripts/populate_preferred_profiles.py
--   deliberately leaves the per-series columns NULL for this reason, and the
--   consensus rebuild has nothing to promote.
--
--   Filling clean.ticker_profile.coupon_rate from an issuer-level figure would
--   stamp the same rate onto every preferred of a multi-series issuer. For
--   most issuers there is exactly one preferred class and the figure is
--   usable; for the ~21% with more than one it is not attributable at all.
--   security_count exposes that ambiguity so a consumer can decide.
--
--   The column is named issuer_liquidation_or_par_value rather than
--   liquidation_preference on purpose: extract_preferred_terms_from_companyfacts
--   falls back to the par/stated-value concepts when no liquidation-preference
--   concept is filed and stores both under one key, so the column mixes real
--   liquidation preferences with par values (observed data is mostly par
--   values < 10, including common-stock par artifacts).
--
-- Read-only: adds a view and its comments. No table, column, or data change,
-- and nothing in the nightly pipeline writes to it.
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
