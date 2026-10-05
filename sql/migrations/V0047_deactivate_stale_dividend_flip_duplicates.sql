-- V0047 deactivate_stale_dividend_flip_duplicates
--
-- ux_security_cik_ticker_type_dividend carries `dividend` in the key, so when
-- raw.company_classification flips an issuer's dividend flag the upsert mints a
-- second row instead of updating the first. populate_reference_tables sweeps
-- the stale twin via _reconcile_instrument_rows, but that sweep did not run to
-- completion for 4 pairs (BTLN, OCAC-RI, OCAC-UN, OCAC-WT), leaving two active
-- rows per (cik, ticker). None of the 8 rows has features, scores or
-- predictions.
--
-- Survivor rule: keep the row whose dividend flag matches the current
-- raw.company_classification (one row per issuer cik); deactivate every other active row for the same
-- (cik, ticker). Rows are deactivated, not deleted, as in V0039. Survivors
-- written without dividend_last_paid get it from the classification, which is
-- what the upsert would have written.

UPDATE reference.securities s
SET active = FALSE, updated_at = now()
WHERE s.active
  AND EXISTS (
      SELECT 1
      FROM reference.securities t
      JOIN raw.company_classification c ON c.cik = t.cik
      WHERE t.cik = s.cik
        AND t.ticker = s.ticker
        AND t.security_id <> s.security_id
        AND t.active
        AND t.dividend = c.dividend
        AND s.dividend IS DISTINCT FROM c.dividend
  );

UPDATE reference.securities s
SET dividend_last_paid = c.dividend_last_paid, updated_at = now()
FROM raw.company_classification c
WHERE c.cik = s.cik
  AND s.active
  AND s.dividend = c.dividend
  AND s.dividend_last_paid IS NULL
  AND c.dividend_last_paid IS NOT NULL;
