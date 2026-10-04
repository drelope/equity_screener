-- =====================================================================
-- V0014 earnings_trajectory
-- Add eps_ttm_growth to model.features.
--
-- A company whose earnings are shrinking is less likely to sustain or
-- grow its dividend. This feature captures the trajectory of TTM EPS
-- by comparing the current TTM against the prior TTM. Negative growth
-- is a classic pre-cut signal.
--
-- The feature is computed in src/crispdm/features.py as:
--   eps_ttm / eps_ttm_prior - 1
-- where eps_ttm_prior is the sum of EPS from quarters 5-8 (the TTM
-- from one year ago). The divisor is guarded so a negative or zero
-- prior base does not produce a misleading ratio.
-- =====================================================================

ALTER TABLE model.features
  ADD COLUMN IF NOT EXISTS eps_ttm_growth NUMERIC;

COMMENT ON COLUMN model.features.eps_ttm_growth IS
  'Earnings trajectory: current TTM EPS divided by prior TTM EPS minus 1. '
  'Negative values indicate shrinking earnings, a classic pre-cut signal. '
  'NULL when the prior TTM base is non-positive or unavailable.';
