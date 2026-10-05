-- V0034 inactive_dividend_cleanup
--
-- Two corrections to reference.securities dividend flags. Both are data
-- corrections rather than schema changes, and both are consequences of the
-- universe-scoping work recorded in the 2026-10-04 data quality audit.
--
-- 1. Inactive securities must not be flagged as dividend payers.
--    370 securities sit at active = FALSE (deactivated by a ticker flip or by
--    _deactivate_referenced_security because they still had downstream child
--    rows) while still carrying dividend = TRUE, because the dividend flag is
--    derived from CIK-level XBRL facts with no reference to `active`
--    (populate_securities never reads `active`; it hardcodes it to TRUE on both
--    the INSERT and the ON CONFLICT DO UPDATE). Every consumer is active-scoped,
--    so these rows are excluded from the universe already, but the flag itself
--    is wrong: it asserts these instruments pay a dividend when the pipeline
--    has already decided not to cover them. Corrected to FALSE so the flag and
--    the coverage decision agree.
--
--    Pre-flight confirmed 0 of the 370 collide with an existing
--    (cik, ticker, security_type, dividend = FALSE) row, so the flip cannot
--    violate ux_security_cik_ticker_type_dividend.
--
-- 2. Five spurious dividend = TRUE duplicates shadow a valid FALSE row.
--    OCAC, OCAC-RI, OCAC-UN, OCAC-WT (Ocean Capital Acquisition Corp, a SPAC
--    whose units/rights/warrants pay no dividend) and BTLN (a derivative) each
--    have two active rows for the same (cik, ticker): a correctly classified
--    dividend = FALSE row written by populate_securities on 2026-09-22 with
--    classify_source populated, and a dividend = TRUE row created 2026-10-04 by
--    a different code path with classify_source and classification_evidence
--    both NULL.
--
--    The TRUE row cannot simply be flipped to FALSE: 4 of the 5 already have a
--    FALSE sibling on the same (cik, ticker, security_type), so the flip would
--    violate the unique index. The demotion the data already encodes is the
--    FALSE row, which stays active. The TRUE duplicates are therefore
--    deactivated rather than deleted, matching the existing
--    _deactivate_referenced_security precedent: all five carry child rows in
--    raw.ticker_profile and fundamentals.periodic_financials, so deleting them
--    would discard real source data. This also removes 5 of the 66 duplicate
--    active-row violations that validate_securities_reference_fk rejects.
--
--    These 5 remain dividend = TRUE at active = FALSE rather than FALSE. That
--    is forced by the unique index: a FALSE sibling already occupies their
--    (cik, ticker, security_type) slot. It is inert, since every consumer
--    filters on active.
--
-- Scope: 370 rows updated in part 1, 5 rows deactivated in part 2. Active
-- dividend payers move from 6,012 to 6,007.
--
-- Not addressed here: 61 further (cik, ticker) pairs hold two active rows that
-- differ only by security_type (dividends = [true, true]). Those are a
-- separate classification-duplication question and need per-issuer review.

-- Part 1: inactive securities are not dividend payers.
UPDATE reference.securities
SET dividend = FALSE,
    updated_at = now()
WHERE active = FALSE
  AND dividend = TRUE;

-- Part 2: deactivate the unevidenced dividend = TRUE duplicates.
UPDATE reference.securities dup
SET active = FALSE,
    updated_at = now()
WHERE dup.active = TRUE
  AND dup.dividend = TRUE
  AND dup.classification_evidence IS NULL
  AND dup.classify_source IS NULL
  AND EXISTS (
      SELECT 1
      FROM reference.securities keep
      WHERE keep.cik = dup.cik
        AND keep.ticker = dup.ticker
        AND keep.dividend = FALSE
  );
