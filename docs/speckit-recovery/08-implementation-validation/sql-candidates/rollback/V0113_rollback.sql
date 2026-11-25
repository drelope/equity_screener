-- ROLLBACK CANDIDATE: NOT APPLIED — V0113 governance event rollback
-- Drops the append-only trigger/function and the governance event table.
-- Export audit.ledger_governance_events first; this destroys governance evidence.
BEGIN;

DROP TRIGGER IF EXISTS ledger_governance_events_append_only
    ON audit.ledger_governance_events;
DROP FUNCTION IF EXISTS audit.prevent_ledger_governance_event_mutation();
DROP TABLE IF EXISTS audit.ledger_governance_events;

COMMIT;
