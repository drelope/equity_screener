-- V0079 retire legal_rights comments
-- Restate the model.scores column comments after legal_rights_score was retired.
--
-- V0070 set the current text when legal_rights_score was the one remaining
-- constant, worth 0.25, leaving a 0.75 measurable subtotal and a 0.50
-- total-weight floor that sat at 0.25 / 0.75 = 0.3333 of score_coverage.
--
-- The weight is now retired: scoring.WEIGHTS no longer carries
-- legal_rights_score, the fillna(0.5) is gone, and the five remaining weights
-- renormalise over the 0.75 they share. The measurable subtotal is the full
-- weight, 1.0, so the 0.50 floor reads as 0.50 of either denominator and
-- composite_score is published iff score_coverage >= 0.50.
--
-- These comments are not decoration: app/column_docs.py resolves them for the
-- dashboard hover help, so a stale relationship is shown to a reader. V0013,
-- V0015 and V0070 stay untouched as the historical record; this file restates
-- the live comments only. No data changes -- score_rank already writes NULL for
-- legal_rights_score because score() no longer sets it.

COMMENT ON COLUMN model.scores.score_coverage IS
  'Share of the composite weight that was present for this security, between 0 '
  'and 1. Every component is measured, so the denominator is the full weight '
  '(1.0); a component a filer did not report simply does not count. Published '
  'so a reader can see how much evidence is behind composite_score rather than '
  'having to infer it from a NULL. 1.0 means every leg was present; 0 means '
  'nothing was measured. composite_score is published when 0.50 of the weight '
  'is present, i.e. iff this column >= 0.50. Written for every row, including '
  'unscored ones, which is the only way to tell a thinly measured security from '
  'one with no data at all.';

COMMENT ON COLUMN model.scores.legal_rights_score IS
  'Retired, permanently NULL. The column was a flat 0.5 imputation carrying '
  '0.25 of the composite weight, so it contributed a constant 0.125 to every '
  'security regardless of evidence. It is no longer part of scoring.WEIGHTS and '
  'score() no longer sets it; score_rank carries the raw column through so the '
  'scheme is visible, but no row has a value.';

COMMENT ON COLUMN model.scores.cvs_coverage IS
  'Share of CVS weight backed by measurement rather than imputation, 0 to 1. '
  'Measured against the full CVS weight, and not comparable with '
  'model.scores.score_coverage, which is the share of the (now equally full) '
  'composite weight present.';
