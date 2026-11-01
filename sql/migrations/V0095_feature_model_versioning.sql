-- V0095: Add feature set and model versioning
BEGIN;

-- Add versioning to model.features
ALTER TABLE model.features 
  ADD COLUMN IF NOT EXISTS feature_set_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS feature_version VARCHAR(32) DEFAULT 'v1';

-- Add model versioning to model.predictions
ALTER TABLE model.predictions 
  ADD COLUMN IF NOT EXISTS model_config_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS training_run_id UUID;

-- Extend audit.source_lineage for model versions
ALTER TABLE audit.source_lineage
  ADD COLUMN IF NOT EXISTS model_version VARCHAR(64),
  ADD COLUMN IF NOT EXISTS feature_set_hash VARCHAR(64);

COMMENT ON COLUMN model.features.feature_set_hash IS 'Hash of feature definitions used to compute this row';
COMMENT ON COLUMN model.features.feature_version IS 'Feature pipeline version';
COMMENT ON COLUMN model.predictions.model_config_hash IS 'Hash of model configuration/priors';
COMMENT ON COLUMN model.predictions.training_run_id IS 'Reference to training run';
COMMENT ON COLUMN audit.source_lineage.model_version IS 'Model version that used this lineage';
COMMENT ON COLUMN audit.source_lineage.feature_set_hash IS 'Feature set hash for traceability';

COMMIT;
