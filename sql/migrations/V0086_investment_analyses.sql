-- V0086 investment-analysis worksheets authored in the Streamlit app
--
-- The "Investment analysis" page is a structured worksheet: 18 workflow steps, ~140
-- fields, defined in code (app/analysis_schema.py). The form itself lives in the JSONB
-- payload so adding or renaming a field is an app change, never a migration; the few
-- summary columns beside it (thesis, recommendation, confidence, risk score) exist only
-- so the saved-analyses list can be read without opening every payload.
--
-- The payload schema is versioned in schema_version; a breaking field change bumps
-- analysis_schema.SCHEMA_VERSION and old rows keep their old shape.

CREATE SCHEMA IF NOT EXISTS analysis;

COMMENT ON SCHEMA analysis IS
    'Investment-analysis worksheets authored in the Streamlit app';

CREATE TABLE IF NOT EXISTS analysis.investment_analyses (
    analysis_id       BIGSERIAL PRIMARY KEY,
    security_id       UUID        NOT NULL REFERENCES reference.securities (security_id),
    ticker            TEXT        NOT NULL,
    status            TEXT        NOT NULL DEFAULT 'draft',
    schema_version    INTEGER     NOT NULL DEFAULT 1,
    payload           JSONB       NOT NULL,
    thesis            TEXT        NOT NULL DEFAULT '',
    recommendation    TEXT,
    confidence        TEXT,
    overall_risk_score INTEGER,
    created_by        TEXT        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_investment_analyses_status
        CHECK (status IN ('draft', 'final')),
    CONSTRAINT chk_investment_analyses_recommendation
        CHECK (recommendation IS NULL OR recommendation IN ('Buy', 'Add', 'Hold', 'Trim', 'Sell')),
    CONSTRAINT chk_investment_analyses_confidence
        CHECK (confidence IS NULL OR confidence IN ('High', 'Medium', 'Low')),
    CONSTRAINT chk_investment_analyses_risk
        CHECK (overall_risk_score IS NULL OR overall_risk_score BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS ix_investment_analyses_security
    ON analysis.investment_analyses (security_id, created_at DESC);

COMMENT ON TABLE analysis.investment_analyses IS
    'One row per saved investment-analysis worksheet; the form is the JSONB payload';
COMMENT ON COLUMN analysis.investment_analyses.security_id IS
    'Security the analysis is about; the ticker column is a denormalised copy for lists';
COMMENT ON COLUMN analysis.investment_analyses.ticker IS
    'Ticker at save time, so the list still reads correctly if a symbol is renamed';
COMMENT ON COLUMN analysis.investment_analyses.status IS
    'draft (work in progress) or final (recommendation reached)';
COMMENT ON COLUMN analysis.investment_analyses.schema_version IS
    'analysis_schema.SCHEMA_VERSION the payload was written under';
COMMENT ON COLUMN analysis.investment_analyses.payload IS
    'Worksheet form: {"version": N, "sections": {section_id: {field_id: value}}}';
COMMENT ON COLUMN analysis.investment_analyses.thesis IS
    'Final-section thesis, denormalised for the list view; max three sentences';
COMMENT ON COLUMN analysis.investment_analyses.recommendation IS
    'Final-section recommendation: Buy, Add, Hold, Trim or Sell';
COMMENT ON COLUMN analysis.investment_analyses.confidence IS
    'Overall confidence from the final section: High, Medium or Low';
COMMENT ON COLUMN analysis.investment_analyses.overall_risk_score IS
    'Risk-decomposition score from step 16, 1 (lowest risk) to 10';
COMMENT ON COLUMN analysis.investment_analyses.created_by IS
    'Operator label recorded when the worksheet was first saved';
COMMENT ON COLUMN analysis.investment_analyses.created_at IS
    'When the worksheet was first saved (UTC)';
COMMENT ON COLUMN analysis.investment_analyses.updated_at IS
    'When the worksheet was last saved (UTC)';
