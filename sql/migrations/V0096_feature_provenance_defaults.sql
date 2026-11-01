-- V0096: Make the feature-provenance defaults match the pipeline.
--
-- V0095 added model.features.feature_version with DEFAULT 'v1', a value the
-- pipeline never used (it writes features_v5). Every row inserted without an
-- explicit version would have been stamped with a retired version, and the
-- existing 9.7M rows all carry that default. The default is corrected here;
-- the historical rows are backfilled by scripts/backfill_feature_provenance.py
-- in batches, because rewriting 9.7M rows inside one migration transaction
-- bloats the table and holds locks for the whole rewrite.
BEGIN;

ALTER TABLE model.features
  ALTER COLUMN feature_version SET DEFAULT 'features_v5';

-- Hash of the model feature definition in src/crispdm/feature_set.py.
ALTER TABLE model.features
  ALTER COLUMN feature_set_hash SET DEFAULT '929658405dbc95be';

COMMENT ON COLUMN model.features.feature_version IS
  'Feature pipeline version (default features_v5; historical v1 rows backfilled in batches)';
COMMENT ON COLUMN model.features.feature_set_hash IS
  'SHA-256 prefix of the sorted model feature list in src/crispdm/feature_set.py';

COMMIT;
