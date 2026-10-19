-- V0088 append-only revisions of investment-analysis worksheets
--
-- Every save overwrote `payload`, so a thesis could only be recovered from a backup and
-- the optimistic-concurrency refusal ("changed in another tab") was a dead end: the
-- older version was simply gone. These revisions make each save permanent, so the
-- refusal becomes recoverable ("reopen the newer version") and the worksheet's history
-- can be read back.
--
-- A trigger rather than an application write: it fires for every writer, not only the
-- Streamlit page, so a script or a future second UI is still audited. It also keeps the
-- append-only path in the same transaction as the save itself, so a revision can never
-- exist without its worksheet or vice versa.

CREATE TABLE IF NOT EXISTS analysis.investment_analysis_revisions (
    revision_id        BIGSERIAL PRIMARY KEY,
    analysis_id        BIGINT      NOT NULL REFERENCES analysis.investment_analyses (analysis_id)
                                   ON DELETE CASCADE,
    schema_version     INTEGER     NOT NULL,
    status             TEXT        NOT NULL,
    payload            JSONB       NOT NULL,
    thesis             TEXT        NOT NULL DEFAULT '',
    recommendation     TEXT,
    confidence         TEXT,
    overall_risk_score INTEGER,
    saved_by           TEXT        NOT NULL,
    saved_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_investment_analysis_revisions_status
        CHECK (status IN ('draft', 'final')),
    CONSTRAINT chk_investment_analysis_revisions_recommendation
        CHECK (recommendation IS NULL
               OR recommendation IN ('Buy', 'Add', 'Hold', 'Trim', 'Sell')),
    CONSTRAINT chk_investment_analysis_revisions_confidence
        CHECK (confidence IS NULL OR confidence IN ('High', 'Medium', 'Low')),
    CONSTRAINT chk_investment_analysis_revisions_risk
        CHECK (overall_risk_score IS NULL OR overall_risk_score BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS ix_investment_analysis_revisions_analysis
    ON analysis.investment_analysis_revisions (analysis_id, revision_id DESC);

COMMENT ON TABLE analysis.investment_analysis_revisions IS
    'One row per save of a worksheet (the first save and every later one); '
    'revision_id rises with each save';
COMMENT ON COLUMN analysis.investment_analysis_revisions.analysis_id IS
    'Worksheet the revision belongs to; deleted with it';
COMMENT ON COLUMN analysis.investment_analysis_revisions.schema_version IS
    'analysis_schema.SCHEMA_VERSION the payload was written under';
COMMENT ON COLUMN analysis.investment_analysis_revisions.status IS
    'draft or final as recorded at that save';
COMMENT ON COLUMN analysis.investment_analysis_revisions.payload IS
    'The worksheet form exactly as saved, so any revision can be reopened';
COMMENT ON COLUMN analysis.investment_analysis_revisions.saved_by IS
    'updated_by for a later save, created_by for the first one';
COMMENT ON COLUMN analysis.investment_analysis_revisions.saved_at IS
    'When this revision was written (UTC)';

CREATE OR REPLACE FUNCTION analysis.record_investment_analysis_revision() RETURNS trigger AS $$
BEGIN
    INSERT INTO analysis.investment_analysis_revisions
        (analysis_id, schema_version, status, payload, thesis, recommendation,
         confidence, overall_risk_score, saved_by)
    VALUES
        (NEW.analysis_id, NEW.schema_version, NEW.status, NEW.payload, NEW.thesis,
         NEW.recommendation, NEW.confidence, NEW.overall_risk_score,
         COALESCE(NEW.updated_by, NEW.created_by));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION analysis.record_investment_analysis_revision() IS
    'Copies each insert/update of investment_analyses into the revisions table';

DROP TRIGGER IF EXISTS trg_investment_analysis_revision ON analysis.investment_analyses;
CREATE TRIGGER trg_investment_analysis_revision
    AFTER INSERT OR UPDATE ON analysis.investment_analyses
    FOR EACH ROW EXECUTE FUNCTION analysis.record_investment_analysis_revision();
