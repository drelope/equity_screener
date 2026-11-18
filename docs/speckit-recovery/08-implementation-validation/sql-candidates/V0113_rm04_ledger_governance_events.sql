-- CANDIDATE: NOT APPLIED — RM-04/RM-05 ledger governance event candidate (V0113)
-- Promotion source: ../manifest-ledger-governance-policy-draft.md
-- APPROVAL-GATES: M1, DEC-002, DEC-003, DEC-005
-- ROLLBACK: rollback/V0113_rollback.sql
-- REHEARSAL: ledger-governance-events-rehearsal-2026-11-16.json (DDL + behavior)
--
-- Purpose: speculative append-only audit trail for legal holds, exports, purge
--          requests, break-glass use, and incidents affecting the V0110 ledger.
--          This records governance decisions; it does NOT implement retention,
--          purge, legal-hold enforcement, or role grants. Append a compensating
--          event instead of mutating history.
--
-- Prerequisites: V0110 audit.run_manifests. Retention period, legal-hold policy,
--                incident runbook, and M1/DEC-002/003/005 approvals remain external.
--
-- Additive-only: creates one table, two indexes, one trigger function, and one
-- append-only trigger.

BEGIN;

CREATE TABLE IF NOT EXISTS audit.ledger_governance_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    run_id TEXT REFERENCES audit.run_manifests(run_id),
    actor TEXT NOT NULL,
    approver TEXT,
    dual_control BOOLEAN NOT NULL DEFAULT FALSE,
    export_ref TEXT,
    post_review_ref TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ledger_governance_event_type_chk CHECK (
        event_type IN (
            'incident_opened',
            'incident_closed',
            'legal_hold_applied',
            'legal_hold_released',
            'export_completed',
            'purge_requested',
            'purge_completed',
            'break_glass_used'
        )
    ),
    CONSTRAINT ledger_governance_event_actor_chk CHECK (btrim(actor) <> ''),
    CONSTRAINT ledger_governance_event_approver_chk CHECK (
        approver IS NULL OR btrim(approver) <> ''
    ),
    CONSTRAINT ledger_governance_event_separation_chk CHECK (
        approver IS NULL OR approver <> actor
    ),
    CONSTRAINT ledger_governance_event_dual_control_chk CHECK (
        event_type NOT IN (
            'legal_hold_applied',
            'legal_hold_released',
            'purge_requested',
            'purge_completed',
            'break_glass_used'
        )
        OR (dual_control AND approver IS NOT NULL)
    ),
    CONSTRAINT ledger_governance_event_purge_export_chk CHECK (
        event_type <> 'purge_completed' OR export_ref IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_ledger_governance_events_run
    ON audit.ledger_governance_events (run_id, recorded_at);

CREATE INDEX IF NOT EXISTS idx_ledger_governance_events_type
    ON audit.ledger_governance_events (event_type, recorded_at);

CREATE OR REPLACE FUNCTION audit.prevent_ledger_governance_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'append-only governance event log: ' || TG_OP
                  || ' is not allowed on ' || TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        ERRCODE = '23000';
END;
$$;

CREATE TRIGGER ledger_governance_events_append_only
BEFORE UPDATE OR DELETE ON audit.ledger_governance_events
FOR EACH ROW EXECUTE FUNCTION audit.prevent_ledger_governance_event_mutation();

COMMIT;
