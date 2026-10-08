-- V0050 quarantine impossible fundamentals values
--
-- A 2026-10-05 audit found rows in fundamentals.periodic_financials whose values
-- cannot be right. They are recorded in audit.quarantined_values and left in
-- place, for the reason V0038 gives: deleting or NULLing them would hide the
-- extractor defect and lose the evidence needed to fix it.
--
--   period_end in the future      315 rows   (worst 2039-08-31)
--   filed before period_end       966 rows   (612 are more than a year early)
--   shares_outstanding <= 0      1050 rows
--   debt < 0                      214 rows
--   liabilities < 0                61 rows
--
-- Unlike V0038, recording is NOT the same as excluding. features.py reads
-- period_end and filed to build the vintage chain, and reads debt for
-- debt_to_ebitda, so those three classes still reach scored securities (153
-- active dividend payers have a row filed before its period ended). A row filed
-- before its period_end is available to an observation date before the period
-- has finished, which is look-ahead. Closing that needs a change to the feature
-- build and so a features_v4, which is not decided here.
--
-- shares_outstanding and liabilities are not read by features.py, so those two
-- classes do not reach the composite.
--
-- Non-integer shares_outstanding (250 rows) is deliberately not quarantined:
-- fractional share counts are legitimate, so it is not wrong on its face.

INSERT INTO audit.quarantined_values (
    table_schema, table_name, column_name, row_key,
    cik, ticker, observed_value, reason, rule
)
SELECT
    'fundamentals', 'periodic_financials', a.column_name,
    concat_ws('|', f.security_id, f.period_end, f.fiscal_period, f.filed),
    s.cik, s.ticker, a.observed_value, a.reason, a.rule
FROM fundamentals.periodic_financials f
JOIN reference.securities s USING (security_id)
CROSS JOIN LATERAL (
    SELECT 'period_end', f.period_end::text,
           'period_end is after the run date, so the period has not ended; the '
           'XBRL context date is forward-dated or mistyped.',
           'period_end > now()::date'
    WHERE f.period_end > now()::date
    UNION ALL
    SELECT 'filed', f.filed::text,
           'filed precedes period_end, so the vintage would be visible to '
           'observation dates before the period finished (look-ahead).',
           'filed < period_end'
    WHERE f.filed < f.period_end
    UNION ALL
    SELECT 'shares_outstanding', f.shares_outstanding::text,
           'a share count of zero or below is not a valid outstanding-share figure.',
           'shares_outstanding <= 0'
    WHERE f.shares_outstanding <= 0
    UNION ALL
    SELECT 'debt', f.debt::text,
           'negative debt; the extractor summed or signed a tag incorrectly. Read by '
           'debt_to_ebitda.',
           'debt < 0'
    WHERE f.debt < 0
    UNION ALL
    SELECT 'liabilities', f.liabilities::text,
           'negative total liabilities is not a valid balance-sheet figure.',
           'liabilities < 0'
    WHERE f.liabilities < 0
) AS a(column_name, observed_value, reason, rule)
ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value)
DO NOTHING;
