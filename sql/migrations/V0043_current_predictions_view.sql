-- V0043 current_predictions
--
-- model.predictions accumulates. Every score_rank invocation stamps a fresh
-- run_id and writes a complete set of rows for its as_of_date, so re-scoring --
-- routine, because a scoring-policy change means every date has to be
-- recomputed -- leaves several complete sets behind for the same
-- (security_id, as_of_date). Nothing but created_at distinguishes them.
--
-- That is not cosmetic. At the latest date two runs currently coexist and
-- disagree on 5,395 of 5,618 securities, and a query without a run filter gets
-- whichever run the planner reaches first, so "the" prediction for a security is
-- arbitrary. Older dates carry up to 7 runs each for the same reason.
--
-- The fix is to stop asking that question rather than to delete the answer.
-- This view exposes the newest run per as_of_date, so a consumer that wants the
-- current prediction has one unambiguous source, while every superseded run
-- stays in the table as the audit trail of which model produced which number.
--
-- Deliberately not done here: pruning superseded runs. That is a retention
-- decision, not an implementation detail, and it is now safe to defer precisely
-- because the view removes the ambiguity that made it tempting -- see the
-- comment on model.predictions in schema.sql.
--
-- "Newest" is created_at descending, tie-broken on run_id so the view is stable
-- when two runs share a transaction timestamp. All rows of one run are written
-- in a single transaction, so created_at is constant within a run.

BEGIN;

CREATE OR REPLACE VIEW model.current_predictions AS
WITH ranked AS (
    SELECT DISTINCT ON (p.as_of_date)
           p.as_of_date,
           p.run_id
    FROM model.predictions p
    ORDER BY p.as_of_date, p.created_at DESC, p.run_id
)
SELECT p.*
FROM model.predictions p
JOIN ranked r
  ON r.as_of_date = p.as_of_date
 AND r.run_id = p.run_id;

COMMENT ON VIEW model.current_predictions IS
    'The newest scoring run for each as_of_date, i.e. the predictions that are '
    'actually current. Use this instead of querying model.predictions directly: '
    'that table is append-only across runs and holds several conflicting sets for '
    'the same security and date, so an unfiltered query returns an arbitrary one. '
    'Superseded runs remain in model.predictions as the audit trail.';

COMMIT;
