-- V0087 record who last saved an investment-analysis worksheet
--
-- created_by only says who first saved the row; every later save overwrites the
-- content, so an audit trail needs the last editor beside it. NULL marks rows written
-- before this migration, which stay readable and correctable on their next save.

ALTER TABLE analysis.investment_analyses
    ADD COLUMN IF NOT EXISTS updated_by TEXT;

COMMENT ON COLUMN analysis.investment_analyses.updated_by IS
    'Operator label recorded when the worksheet was last saved; NULL before V0087';
