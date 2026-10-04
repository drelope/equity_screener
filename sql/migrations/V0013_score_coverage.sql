-- =====================================================================
-- V0013 score_coverage
-- Publish how much of a composite score is evidence.
--
-- model.scores.composite_score used to be a plain weighted sum of the six
-- components in src/crispdm/scoring.py, so a single NULL input NaN'd the whole
-- row. On the latest feature date that left 4,127 of 5,443 securities (75.8%)
-- with no score at all: the column was technically populated and practically
-- unusable, and the app's Median Score read N/A.
--
-- The composite is now renormalised over whichever components are present, so a
-- partial row scores on the same 0-1 scale as a complete one, and a row whose
-- present weight falls below the floor is left NULL rather than published as a
-- confident number. That is a judgement about how much evidence is enough, and
-- a judgement is only reviewable if the reader can see the input. This column
-- is that input: the share of the *measurable* weight that was present, 0 to 1.
--
-- Deliberately measured against the measurable subtotal (0.70 of the weight),
-- not against sum(WEIGHTS) (1.0). legal_rights_score is imputed to a flat 0.5
-- for every security and valuation_score is a hardcoded 0.5, together 0.30 of
-- the weight. Both are always present, so counting them would put a 0.30 floor
-- under every coverage figure and a security with nothing measured at all
-- would still read 43% covered. Coverage is meant to answer "how much of this
-- score is a measurement", and a placeholder is never a measurement.
--
-- The floor and this column are on different denominators on purpose, and the
-- gap is large. The floor is 0.50 of the *total* weight; this column is a share
-- of the *measurable* 0.70. Because the two constant components are always
-- present, the floor sits at 0.20 of the measurable weight, i.e. 28.6% coverage.
-- On the latest feature date that is the difference between scoring 5,163 of
-- 5,443 securities and scoring 2,868: a floor stated on the measurable subtotal
-- would be a stricter rule wearing the same label. Putting the floor on the
-- total keeps 0.50 meaning what a reader expects, and this column is what lets
-- them see the evidence behind each score rather than infer it from a NULL.
--
-- So the pairing is not a single threshold: composite_score is NOT NULL whenever
-- present total weight >= 0.50, which is score_coverage >= 0.2857.
-- =====================================================================

ALTER TABLE model.scores
  ADD COLUMN IF NOT EXISTS score_coverage numeric(6,4);

COMMENT ON COLUMN model.scores.score_coverage IS
  'Share of the measurable composite weight (0.70 of 1.0, excluding the '
  'constant legal_rights_score and valuation_score components) that was '
  'present for this security, between 0 and 1. Published so a reader can see '
  'how much evidence is behind composite_score rather than having to infer it '
  'from a NULL. 1.0 means every measured leg was present; 0 means the composite '
  'rests on the two hardcoded components alone. Note the floor is NOT 0.50 '
  'here: composite_score is published when 0.50 of the total weight is present, '
  'which is 0.2857 of this column. Written for every row, including unscored '
  'ones, which is the only way to tell a thinly measured security from one with '
  'no data at all.';
