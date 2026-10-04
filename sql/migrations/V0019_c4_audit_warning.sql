-- C4 audit warning (specification section 5.5, fallback branch).
--
-- Section 5.5 says that when a filer discloses no contractual maturity
-- schedule, C4 is called Safe only if Quick Liquidity >= 1.20x and Net Debt /
-- EBITDA <= 2.0x, and otherwise "flags an audit warning".
--
-- That fallback is a data-quality statement, not a dividend-safety verdict, so
-- it must not reach the override. With 3,915 of 4,907 securities disclosing no
-- maturity ladder, failing C4 closed on absent footnote data put every one of
-- them at C4-true; combined with any second breach that printed RED for 90% of
-- the universe. That is publishing insolvency verdicts on the grounds that an
-- integration was never built.
--
-- This column records which rows are unverifiable rather than clear. Without it
-- "C4 did not fire" is indistinguishable from "C4 could not be evaluated",
-- which are very different statements about the same missing column.
BEGIN;

ALTER TABLE model.scores
  ADD COLUMN IF NOT EXISTS c4_audit_warning BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN model.scores.c4_audit_warning IS
  'True where C4 (Maturity Cliff) could not be evaluated at all: the filer '
  'discloses no maturity ladder AND the section 5.5 Quick Liquidity / Net Debt '
  'fallback proxies were also missing. False means either the ladder was '
  'present, or the fallback cleared it. An audit warning never reaches '
  'override_flag -- see regime_pipeline._c4_fallback_verdict.';

INSERT INTO public.schema_migrations(version, name)
VALUES (19, 'c4_audit_warning')
ON CONFLICT (version) DO NOTHING;

COMMIT;