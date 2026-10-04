-- =====================================================================
-- V0008 model_run_imbalance_metrics
-- audit.model_runs recorded precision, recall, f1, pr_auc, roc_auc and
-- accuracy. On this label population (93.6% positive) accuracy and recall
-- are both ~0.94 for the trivial "always predict sustainable" classifier,
-- so the recorded row cannot distinguish a trained model from that baseline.
--
-- The run record is the durable Go/No-Go evidence, so the metrics that
-- actually expose minority-class performance have to be stored with it:
-- balanced_accuracy, the per-class precision/recall, and the negative-class
-- support. gate_passed and readiness record the verdict itself, including
-- the completeness failure that must block a Go.
-- =====================================================================

DO $migration$
BEGIN

  ALTER TABLE audit.model_runs
    ADD COLUMN IF NOT EXISTS balanced_accuracy NUMERIC,
    ADD COLUMN IF NOT EXISTS positive_precision NUMERIC,
    ADD COLUMN IF NOT EXISTS positive_recall NUMERIC,
    ADD COLUMN IF NOT EXISTS negative_precision NUMERIC,
    ADD COLUMN IF NOT EXISTS negative_recall NUMERIC,
    ADD COLUMN IF NOT EXISTS negative_support INTEGER,
    ADD COLUMN IF NOT EXISTS positive_support INTEGER,
    ADD COLUMN IF NOT EXISTS positive_rate NUMERIC,
    ADD COLUMN IF NOT EXISTS n_train_rows INTEGER,
    ADD COLUMN IF NOT EXISTS n_test_rows INTEGER,
    ADD COLUMN IF NOT EXISTS n_feature_rows BIGINT,
    ADD COLUMN IF NOT EXISTS baseline_balanced_accuracy NUMERIC,
    ADD COLUMN IF NOT EXISTS baseline_pr_auc NUMERIC,
    ADD COLUMN IF NOT EXISTS gate_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS readiness VARCHAR(16),
    ADD COLUMN IF NOT EXISTS feature_completeness JSONB,
    ADD COLUMN IF NOT EXISTS gate_detail JSONB;

  COMMENT ON COLUMN audit.model_runs.balanced_accuracy IS
    'Mean of per-class recall. Unlike accuracy and recall on a 93.6%-positive '
    'label set, this cannot be maximised by always answering the majority '
    'class, so it is the primary comparison against the naive baseline.';

  COMMENT ON COLUMN audit.model_runs.negative_recall IS
    'Recall on the minority (non-sustainable) class: the fraction of genuine '
    'failures the model actually catches. A model that rides the majority '
    'class scores ~0 here.';

  COMMENT ON COLUMN audit.model_runs.readiness IS
    'go | no_go. A go additionally requires feature completeness: a run on '
    'placeholder features is recorded as no_go regardless of its metrics.';

  COMMENT ON COLUMN audit.model_runs.gate_detail IS
    'Per-criterion gate comparison against the naive baseline, including '
    'which criterion was missed on a failure';

END
$migration$;
