-- =====================================================================
-- V0007 feature_price_quality
-- An implausible dividend_yield is usually not a bad dividend, it is a bad
-- DENOMINATOR. Two distinct price defects both produce nonsense yields, and
-- conflating them with "the calculation is wrong" hides which one is real:
--
--   1. Split-adjustment artifacts. Providers backfill unadjusted history
--      across reverse splits, so a pre-split row carries a post-split-scale
--      price: BINI at $1.02tn, WHLR at $250bn, ADTX at $10bn. Against a
--      real dividend these yield ~1e-12, which the yield filter cannot
--      distinguish from a genuinely tiny dividend.
--   2. Sub-penny / shell prices. GNOLF, GTCH and 30+ shells carry a
--      $0.00004 close, where one $0.0001 tick is 1000% of the price and
--      the ratio is pure quantisation noise. These are real observations of
--      an economically meaningless denominator, not arithmetic errors.
--
-- The yield bounds alone are not a price-quality rule, so this migration
-- records the price verdict on the row itself:
--
--   price_quality        ok | split_artifact | sub_penny
--   price_quality_rule   the specific rule that fired, for audit
--   raw_current_price    the price as fetched, never overwritten
--   raw_dividend_yield   the computed yield before any exclusion
--
-- The raw_* columns are deliberately denormalised duplicates: the point is
-- that a reviewer can reconstruct exactly what the provider said without
-- re-deriving it, and without trusting the filtered columns. Excluding a
-- row must never destroy the evidence for why it was excluded.
--
-- Detection is relative to each security's own price history rather than a
-- global dollar ceiling, because a global ceiling cannot separate a
-- reverse-split artifact from a genuinely expensive share: BRK-A trades
-- near $809,000 and PAVS near $490,000, both real, while BINI's median is
-- $1.50. A ratio-to-own-median test separates them cleanly.
-- =====================================================================

DO $migration$
BEGIN

  ALTER TABLE model.features
    ADD COLUMN IF NOT EXISTS price_quality VARCHAR(32),
    ADD COLUMN IF NOT EXISTS price_quality_rule VARCHAR(64),
    ADD COLUMN IF NOT EXISTS yield_exclusion_reason VARCHAR(64),
    ADD COLUMN IF NOT EXISTS raw_current_price NUMERIC,
    ADD COLUMN IF NOT EXISTS raw_annual_dividend NUMERIC,
    ADD COLUMN IF NOT EXISTS raw_dividend_yield NUMERIC;

  COMMENT ON COLUMN model.features.price_quality IS
    'Verdict on current_price as a yield denominator: ok, split_artifact '
    '(price inconsistent with this security''s own history, typically an '
    'unadjusted pre-reverse-split row), or sub_penny (price below one tick, '
    'so the ratio is quantisation noise). NULL until build_features runs.';

  COMMENT ON COLUMN model.features.price_quality_rule IS
    'The concrete rule that produced a non-ok price_quality, e.g. '
    'price_below_floor or price_gt_50x_own_median, so an exclusion can be '
    'audited and the rule tuned without re-deriving the verdict';

  COMMENT ON COLUMN model.features.yield_exclusion_reason IS
    'Set when dividend_yield fell outside the plausible band: '
    'yield_above_max or yield_below_min. Kept separate from '
    'price_quality_rule because a bad numerator (e.g. a per-share amount '
    'reported in whole dollars) produces an impossible yield on a perfectly '
    'good price, and attributing that to the price would mislabel the defect';

  COMMENT ON COLUMN model.features.raw_current_price IS
    'current_price exactly as fetched from the provider, retained even when '
    'the row is excluded, so the exclusion is reviewable';

  COMMENT ON COLUMN model.features.raw_annual_dividend IS
    'annual_dividend as computed before any plausibility filter, retained '
    'even when the row is excluded, so the numerator behind a rejected '
    'yield stays auditable';

  COMMENT ON COLUMN model.features.raw_dividend_yield IS
    'dividend_yield as computed before any plausibility or price-quality '
    'filter, retained for the same audit reason';

  -- The feature query filters on price quality every run, so index it.
  CREATE INDEX IF NOT EXISTS idx_features_price_quality
    ON model.features(price_quality);

END
$migration$;
