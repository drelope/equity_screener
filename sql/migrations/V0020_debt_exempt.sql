-- EXEMPT notation for the debt-bearing circuit breakers (specification
-- section 5.5 / C2 and C3).
--
-- Net Debt / EBITDA and Interest Coverage are undefined for a firm carrying no
-- interest-bearing instruments. The layer now reports such a firm EXEMPT --
-- a pass with a notation -- rather than failing C2 and C3 closed on the
-- absence of a ratio that has no meaning for them.
--
-- Fail-closed is untouched where it belongs: a filer whose `debt` balance is
-- present and positive has instruments, so a missing ratio on that firm is a
-- genuine disclosure gap and still fails closed. The precondition keys on
-- debt *presence*, never on the ratio being missing.
--
-- The notation is persisted because a pass and an exemption are different
-- claims. Without it, "this firm's leverage cleared the gate" and "this firm
-- has no leverage to clear" are the same observation, and the second one looks
-- like a clean bill of health that was never tested.
BEGIN;

ALTER TABLE model.scores
  ADD COLUMN IF NOT EXISTS debt_exempt BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN model.scores.debt_exempt IS
  'True where C2 (Net Debt/EBITDA) and C3 (Interest Coverage) did not apply '
  'because model.features.debt is absent or zero: the filer reports no '
  'interest-bearing instruments. Those levers pass rather than fail closed. '
  'Always false when the debt column was unavailable, so a build that dropped '
  'the column cannot exempt the universe. See '
  'regime_pipeline._has_reportable_debt.';

INSERT INTO public.schema_migrations(version, name)
VALUES (20, 'debt_exempt')
ON CONFLICT (version) DO NOTHING;

COMMIT;