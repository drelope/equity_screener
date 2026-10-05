-- V0044 current_predictions_per_security
--
-- Corrects the view definition added in V0043, which resolved "current" per
-- *run* rather than per *security*.
--
-- V0043 picked the newest run for each as_of_date and returned all of its rows.
-- That is wrong wherever a newer run wrote only a few carry-forward rows at an
-- older date: feature carry-forward means each run writes a small number of rows
-- at earlier as_of_dates, so the newest run shadowed the fuller run beneath it
-- and the view reported 20 rows for 2026-10-01 where 5,430 predictions exist.
-- A consumer reading that would conclude most securities have no prediction on
-- that date.
--
-- The resolution has to be per (security_id, as_of_date): for each security and
-- date, the most recent run that actually has a row for it. A security absent
-- from the newest run keeps its newest available prediction rather than
-- disappearing, which is what makes the view usable as "the current prediction"
-- for the whole warehouse rather than only for the securities the last run
-- happened to touch.
--
-- The effect is that the view's per-date row counts now equal the per-date
-- coverage of model.scores (5,430 / 4,909 / 5,445 for 2026-10-01 / 09-30 /
-- 09-29), which is the consistency the per-run version could not produce.

BEGIN;

CREATE OR REPLACE VIEW model.current_predictions AS
SELECT DISTINCT ON (p.security_id, p.as_of_date) p.*
FROM model.predictions p
ORDER BY p.security_id, p.as_of_date, p.created_at DESC, p.run_id;

COMMENT ON VIEW model.current_predictions IS
    'For each security and as_of_date, the prediction from the most recent run '
    'that has a row for it. Use this instead of querying model.predictions '
    'directly: that table is append-only across runs and holds several '
    'conflicting sets for the same security and date, so an unfiltered query '
    'returns an arbitrary one. Resolution is per security rather than per run, '
    'because a newer run may cover only part of an older date -- carry-forward '
    'rows -- and dropping the rest would hide securities that still have a '
    'current prediction there. Superseded runs remain in model.predictions as '
    'the audit trail.';

COMMIT;
