-- V0105: Re-key fundamentals quarantine entries whose security was re-keyed.
--
-- Nine securities (AREB, UUU, PCTTU, SOUL, ALMU, CJMB, PW, ERNA, TDACU) were
-- re-keyed to a successor security_id after the quarantine entries were written.
-- audit.quarantined_values keys a parked value as
-- security_id|period_end|fiscal_period|filed, so 22 unresolved entries still
-- carried the retired id and matched no row, and
-- test_quarantined_fundamentals_values_are_left_in_place reported them as erased.
-- They were not: the identical value is still held under the successor id
-- (checked before this migration: 22 of 22 match on key and value).
--
-- Same repair as V0093: rewrite the key to the successor, found by the unique
-- (ticker, cik) the entry itself records. Unresolved entries only; resolved ones
-- are history and stay as written. Where the successor already holds its own
-- unresolved entry for the same value, the stale one is closed with a note and
-- kept (the unique key forbids a rewrite), never deleted.
BEGIN;

UPDATE audit.quarantined_values q
SET resolved_at = now(),
    resolution_note = 'duplicate of the successor entry after the security was re-keyed; '
                      'the same value is still parked under the successor id'
FROM reference.securities s
WHERE q.resolved_at IS NULL
  AND q.table_schema = 'fundamentals'
  AND s.ticker = q.ticker
  AND s.cik = q.cik
  AND NOT EXISTS (SELECT 1 FROM reference.securities o
                  WHERE o.security_id::text = split_part(q.row_key, '|', 1))
  AND EXISTS (
      SELECT 1 FROM audit.quarantined_values w
      WHERE w.table_schema = q.table_schema
        AND w.table_name = q.table_name
        AND w.column_name = q.column_name
        AND w.observed_value = q.observed_value
        AND w.resolved_at IS NULL
        AND w.row_key = s.security_id::text || substring(q.row_key from 37));

UPDATE audit.quarantined_values q
SET row_key = s.security_id::text || substring(q.row_key from 37)
FROM reference.securities s
WHERE q.resolved_at IS NULL
  AND q.table_schema = 'fundamentals'
  AND s.ticker = q.ticker
  AND s.cik = q.cik
  AND NOT EXISTS (SELECT 1 FROM reference.securities o
                  WHERE o.security_id::text = split_part(q.row_key, '|', 1))
  AND EXISTS (
      SELECT 1 FROM fundamentals.periodic_financials f
      WHERE concat_ws('|', f.security_id, f.period_end, f.fiscal_period, f.filed)
            = s.security_id::text || substring(q.row_key from 37)
        AND CASE q.column_name
              WHEN 'period_end' THEN f.period_end::text
              WHEN 'filed' THEN f.filed::text
              WHEN 'shares_outstanding' THEN f.shares_outstanding::text
              WHEN 'debt' THEN f.debt::text
              WHEN 'liabilities' THEN f.liabilities::text
            END = q.observed_value);

DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n
    FROM audit.quarantined_values q
    WHERE q.resolved_at IS NULL
      AND q.table_schema = 'fundamentals'
      AND NOT EXISTS (
          SELECT 1 FROM fundamentals.periodic_financials f
          WHERE concat_ws('|', f.security_id, f.period_end, f.fiscal_period, f.filed) = q.row_key
      );
    IF n > 0 THEN
        RAISE EXCEPTION 'V0105: % unresolved fundamentals quarantine entries still unmatched', n;
    END IF;
END $$;

COMMIT;
