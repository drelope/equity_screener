-- =====================================================================
-- V0015 regime_layer
-- Publish the market-regime classification, the CVS, and the override flag.
--
-- Implements the storage half of economic_credit_cycle_dividend_regime.md.
-- The logic lives in src/crispdm/regime.py and is pinned by tests/test_regime.py;
-- this migration only makes its output readable by anything that queries
-- model.scores directly. Nothing here changes a score.
--
-- Why publish the inputs rather than only the answers:
--
--   credit_environments are five overlapping bands keyed on C_level and
--   C_delta. They are resolved by precedence, not by first match, so the
--   winner is not recoverable from the bands alone -- a state can satisfy
--   two rows and lose on the stricter one. The resolved label is stored.
--
--   cvs_tier is stored next to cvs_score because the tier is NOT a pure
--   function of the score. Section 4.5 gates Strong on three measured
--   metrics, so a row at CVS 20 with no maturity schedule is Moderate,
--   not Strong. A consumer that re-derives the tier from the score alone
--   will disagree with the scorer on exactly the rows that carry the
--   evidence gap, which is where being wrong matters.
--
--   cvs_missing_core lists the core leverage metrics that were absent, so
--   "why is this unscored" is answerable from the row.
--
-- macro_vintage is the point-in-time column, and it is the whole reason
-- this layer cannot be evaluated without it. Section 9 of the design doc
-- requires a row to join on the vintage published as of as_of_date, not
-- the current vintage. A NULL here means "no macro feed was available on
-- this date", which the scorer maps to the Transition baseline (section
-- 5.4), not to any easing assumption.
--
--   regime_gate_reason records why the layer did not rescale composite_score.
-- It is the difference between "computed nothing" and "found nothing wrong",
-- which are otherwise indistinguishable in a table whose score column did not
-- move. An inert layer that looked identical to a clean bill of health is the
-- failure mode this layer is most likely to produce, because most of its
-- inputs do not exist in the warehouse yet.
--
--   breakers_unavailable names the circuit breakers excluded from the override
-- for want of a source. The override is computed from the remaining levers, so
-- a GREEN flag here is a claim from three of five conditions and the reader
-- cannot see that from the flag alone.
--
-- Nothing in this migration is NOT NULL. Every column is nullable because
-- every one of them is NULL-able by design: composite_score is NULL for a
-- row under MIN_PRESENT_WEIGHT, and the layer is downstream of that and
-- must not manufacture a value for it.
-- =====================================================================

ALTER TABLE model.scores
  ADD COLUMN IF NOT EXISTS market_regime VARCHAR(32),
  ADD COLUMN IF NOT EXISTS credit_environment VARCHAR(32),
  ADD COLUMN IF NOT EXISTS credit_modifier NUMERIC(6,4),
  ADD COLUMN IF NOT EXISTS override_flag VARCHAR(16),
  ADD COLUMN IF NOT EXISTS score_cap NUMERIC(6,4),
  ADD COLUMN IF NOT EXISTS cvs_score NUMERIC(6,2),
  ADD COLUMN IF NOT EXISTS cvs_coverage NUMERIC(6,4),
  ADD COLUMN IF NOT EXISTS cvs_tier VARCHAR(16),
  ADD COLUMN IF NOT EXISTS cvs_missing_core VARCHAR(64),
  ADD COLUMN IF NOT EXISTS macro_vintage DATE,
  ADD COLUMN IF NOT EXISTS breakers_unavailable VARCHAR(32),
  ADD COLUMN IF NOT EXISTS regime_gate_reason VARCHAR(160);

COMMENT ON COLUMN model.scores.market_regime IS
  'Economic/credit phase-space classification: Expansion, Late Cycle, '
  'Transition, Slowdown, Recession or Recovery. Closed six-value vocabulary '
  'enforced by CANONICAL_REGIMES in src/crispdm/regime.py. NULL when the '
  'regime layer did not run for this row.';
COMMENT ON COLUMN model.scores.credit_environment IS
  'Credit-deterioration band used to pick the modifier row: Accommodative, '
  'Normal, Recovery, Velocity Squeeze or Acute Crunch. Resolved by '
  'precedence over overlapping bands, so it is stored rather than '
  're-derived from the macro inputs.';
COMMENT ON COLUMN model.scores.credit_modifier IS
  'Multiplier from CREDIT_MODIFIER_TABLE, between 0 and 1, applied to '
  'composite_score BEFORE the override cap. For an unscorable CVS this is '
  'the provisional 0.85/0.65 penalty of section 5.3, never 1.00.';
COMMENT ON COLUMN model.scores.override_flag IS
  'Dividend-safety circuit-breaker outcome: GREEN, YELLOW, SYSTEMIC_RED or '
  'RED. A NULL input for a lever that HAS a source counts as breached, so a '
  'row whose coverage is unknown for one company still fails closed. A lever '
  'with no source at all is excluded from the count instead and named in '
  'breakers_unavailable -- failing closed on a missing integration would '
  'publish a verdict about our ingestion as though it were about the filer.';
COMMENT ON COLUMN model.scores.score_cap IS
  'Override ceiling for this row from OVERRIDE_CAPS: 1.00 GREEN, 0.45 '
  'YELLOW, 0.25 SYSTEMIC_RED, 0.20 RED. The published composite is '
  'min(composite_score * credit_modifier, score_cap); the cap is applied '
  'second so a capped row lands on the ceiling exactly, not below it.';
COMMENT ON COLUMN model.scores.cvs_score IS
  'Company Credit Vulnerability Score, 0 to 100, higher is worse. NULL when '
  'the core evidence floor fails. Absent credit_rating contributes an '
  'imputed 50.0 across 15% of the weight, which puts a permanent +7.5 point '
  'floor under every row in the universe; see section 4.4.';
COMMENT ON COLUMN model.scores.cvs_coverage IS
  'Share of CVS weight backed by measurement rather than imputation, 0 to 1. '
  'Cannot be compared with model.scores.score_coverage, which is measured '
  'against the 0.70 measurable composite subtotal, not the full weight.';
COMMENT ON COLUMN model.scores.cvs_tier IS
  'strong, moderate, high or unscorable. NOT derivable from cvs_score alone: '
  'strong additionally requires net_debt_to_ebitda, interest_coverage AND '
  'refinancing_wall to all be measured (section 4.5). unscorable is a separate '
  'state, not a score of 100: it means the core evidence floor failed, and it '
  'is stored as a label precisely because an unscorable row must never be '
  'sorted as though it had been measured.';
COMMENT ON COLUMN model.scores.cvs_missing_core IS
  'Comma-separated core leverage metrics absent at compute time, from '
  'net_debt_to_ebitda and interest_coverage. Empty when both were present. '
  'Presence here with a non-NULL cvs_score means one leg was missing but '
  'the floor was still met.';
COMMENT ON COLUMN model.scores.macro_vintage IS
  'As-of date of the macro vintage used. Section 9 forbids joining on the '
  'current vintage: a historical score reproduced with today''s revised '
  'GDP is a look-ahead. NULL means no macro vintage was available, which '
  'scores as the Transition baseline rather than as an easing assumption.';
COMMENT ON COLUMN model.scores.breakers_unavailable IS
  'Comma-separated circuit breakers excluded from the override because the '
  'warehouse has no source for them, currently C4 and C5. A GREEN here rests '
  'on three of five levers and is a weaker claim than the flag alone shows, '
  'so the exclusions travel with the verdict.';
COMMENT ON COLUMN model.scores.regime_gate_reason IS
  'Why the layer did not rescale composite_score: macro_feed_absent, '
  'cvs_inputs_incomplete, circuit_breakers_unevaluable, comma-separated. '
  'NULL means every input the layer needs was present. This column is what '
  'distinguishes an inert layer from a broken one -- without it, a run that '
  'computed nothing and a run that found nothing wrong look identical.';

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_score_cap_range;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_score_cap_range
    CHECK (score_cap IS NULL OR (score_cap >= 0 AND score_cap <= 1));

-- The final-score invariant, enforced where the numbers live.
-- min(composite_score * credit_modifier, score_cap) must hold for every
-- published row. The layer applies the modifier then the cap deliberately --
-- capping first would leave a capped row strictly below its ceiling whenever
-- the modifier is below 1. Stated as an invariant so a future writer cannot
-- reorder the two operations and quietly change every capped score.
ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_final_score_invariant;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_final_score_invariant
    CHECK (
      credit_modifier IS NULL
      OR score_cap IS NULL
      OR composite_score IS NULL
      OR composite_score <= score_cap + 0.0001
    );

-- The closed vocabularies are constraints, not comments. A CHECK is the
-- cheapest thing in the warehouse that turns a spec into an invariant, and
-- these are exactly the values tests/test_regime.py already pins in Python.
ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_market_regime;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_market_regime
    CHECK (market_regime IS NULL OR market_regime IN (
      'Expansion', 'Late Cycle', 'Transition',
      'Slowdown', 'Recession', 'Recovery'
    ));

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_credit_environment;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_credit_environment
    CHECK (credit_environment IS NULL OR credit_environment IN (
      'Accommodative', 'Normal', 'Recovery',
      'Velocity Squeeze', 'Acute Crunch'
    ));

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_cvs_tier;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_cvs_tier
    CHECK (cvs_tier IS NULL OR cvs_tier IN ('strong', 'moderate', 'high', 'unscorable'));

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_override_flag;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_override_flag
    CHECK (override_flag IS NULL OR override_flag IN (
      'GREEN', 'YELLOW', 'SYSTEMIC_RED', 'RED'
    ));

-- Range checks on the three numeric columns, for the same reason. A modifier
-- above 1.0 would be a bug that silently inflates a score, and a negative
-- CVS would read as pristine credit; both are worth a constraint rather than a
-- dashboard check.
ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_credit_modifier_range;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_credit_modifier_range
    CHECK (credit_modifier IS NULL OR (credit_modifier >= 0 AND credit_modifier <= 1));

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_cvs_score_range;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_cvs_score_range
    CHECK (cvs_score IS NULL OR (cvs_score >= 0 AND cvs_score <= 100));

ALTER TABLE model.scores
  DROP CONSTRAINT IF EXISTS chk_scores_cvs_coverage_range;
ALTER TABLE model.scores
  ADD CONSTRAINT chk_scores_cvs_coverage_range
    CHECK (cvs_coverage IS NULL OR (cvs_coverage >= 0 AND cvs_coverage <= 1));

-- Index for the consumer-side exclusion filter. The design doc's section 6.3
-- "Mandatory Universe Exclusion" is a screener/report concern, not something
-- this warehouse can enforce: a position-size cap is portfolio state, and the
-- database has no holdings table and no knowledge of a book. Storing the flag
-- and indexing it is what the warehouse owes the consumer; the decision
-- belongs to whoever holds positions.
CREATE INDEX IF NOT EXISTS ix_scores_override_flag
  ON model.scores (as_of_date, override_flag)
  WHERE override_flag IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_scores_market_regime
  ON model.scores (as_of_date, market_regime)
  WHERE market_regime IS NOT NULL;
