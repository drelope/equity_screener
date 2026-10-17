-- V0082 resolve orphaned filed quarantine entries
--
-- V0078 deleted the 354 fundamentals.periodic_financials rows whose period_end
-- was in the future and resolved the 315 period_end-column quarantine entries
-- for those rows. It did not resolve the `filed < period_end` entries V0050 had
-- raised for the same rows, so 315 `filed` entries were left open pointing at
-- rows that no longer exist. That breaks the registry invariant enforced by
-- tests/test_quarantine_registry.py -- an unresolved entry must still have its
-- row -- which is how the defect was found: the change to V0078 was committed
-- without running that test.
--
-- The rows are gone for a good reason (a period that has not ended cannot have
-- been reported), so the entries are resolved rather than the rows resurrected,
-- with a note recording why the evidence was removed. The row key embeds
-- period_end in field 2, so the orphaned entries are matched precisely by that
-- date being in the future rather than by "row missing", which would also catch
-- unrelated churn.
--
-- 315 entries at this writing, period_end 2026-12-31 .. 2039-08-31.

UPDATE audit.quarantined_values q
SET resolved_at = now(),
    resolution_note =
        'Resolved by V0082: V0078 deleted this row because its period_end was '
        'after the run date, and with it the filed value this entry recorded. A '
        'period that has not ended cannot have been reported, so the row was '
        'unusable rather than merely early and there is no corrected value to '
        'keep. The period_end-column entry for the same row was already closed '
        'by V0078; this closes the filed-column entry V0050 raised alongside it.'
WHERE q.resolved_at IS NULL
  AND q.table_schema = 'fundamentals'
  AND q.table_name = 'periodic_financials'
  AND q.column_name = 'filed'
  AND split_part(q.row_key, '|', 2)::date > CURRENT_DATE;
