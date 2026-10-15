-- =====================================================================
-- V0070 measurable subtotal comments
-- Restate the coverage column comments after valuation_score became real.
--
-- V0013 set the model.scores.score_coverage comment when the measurable
-- subtotal was 0.70 of the weight: legal_rights_score (imputed 0.5) and
-- valuation_score (hardcoded 0.5) were the two constants worth 0.30, so the
-- 0.50 total-weight floor sat at 0.20 / 0.70 = 0.2857 of the column.
--
-- WS13 Phase 2 replaced the valuation_score placeholder with a real
-- point-in-time percentile blend (scoring.VALUATION_PARTS: 0.4 earnings yield,
-- 0.4 FCF yield, 0.2 price-to-book inverted). valuation_score is now measured,
-- so it moved into scoring.MEASURABLE; legal_rights_score is the only constant
-- left, worth 0.25, and the measurable subtotal is 0.75. The same 0.50
-- total-weight floor now sits at 0.25 / 0.75 = 0.3333 of this column.
--
-- V0013 and V0015 stay untouched as the historical record; this file restates
-- the live column comments so the descriptions match the current weights.
-- =====================================================================

COMMENT ON COLUMN model.scores.score_coverage IS
  'Share of the measurable composite weight (0.75 of 1.0, excluding the '
  'constant legal_rights_score component) that was present for this security, '
  'between 0 and 1. Published so a reader can see how much evidence is behind '
  'composite_score rather than having to infer it from a NULL. 1.0 means every '
  'measured leg was present; 0 means the composite rests on the hardcoded '
  'legal_rights_score alone. Note the floor is NOT 0.50 here: composite_score '
  'is published when 0.50 of the total weight is present, which is 0.3333 of '
  'this column. Written for every row, including unscored ones, which is the '
  'only way to tell a thinly measured security from one with no data at all.';

COMMENT ON COLUMN model.scores.cvs_coverage IS
  'Share of CVS weight backed by measurement rather than imputation, 0 to 1. '
  'Cannot be compared with model.scores.score_coverage, which is measured '
  'against the 0.75 measurable composite subtotal, not the full weight.';
