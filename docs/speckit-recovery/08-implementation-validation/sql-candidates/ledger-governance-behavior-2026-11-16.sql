\set ON_ERROR_STOP 0
SET ROLE manifest_writer;
INSERT INTO audit.run_manifests (run_id, run_type, created_at_utc, status, manifest_hash, manifest_json)
VALUES ('gov-run-1','score', now(), 'created', 'h1', '{"run_id":"gov-run-1"}'::jsonb);
SELECT 'writer_insert_manifest_ok';
UPDATE audit.run_manifests SET status='x' WHERE run_id='gov-run-1';
SELECT 'writer_update_expect_denied';
SELECT count(*) FROM audit.run_manifests;
RESET ROLE;
SET ROLE manifest_reader;
SELECT count(*) AS reader_select_ok FROM audit.run_manifests;
INSERT INTO audit.run_manifests (run_id, run_type, created_at_utc, status, manifest_hash, manifest_json)
VALUES ('reader-bad','score', now(), 'created', 'h', '{}'::jsonb);
SELECT 'reader_insert_expect_denied';
RESET ROLE;
SET ROLE ledger_auditor;
SELECT count(*) AS auditor_migrations FROM public.schema_migrations;
SELECT count(*) AS auditor_manifests FROM audit.run_manifests;
RESET ROLE;
INSERT INTO audit.ledger_governance_events (event_type, run_id, actor, approver, dual_control, details)
VALUES ('incident_opened','gov-run-1','alice',NULL,false,'{"ticket":"INC-1"}'::jsonb);
INSERT INTO audit.ledger_governance_events (event_type, run_id, actor, approver, dual_control)
VALUES ('legal_hold_applied','gov-run-1','alice','alice',true);
INSERT INTO audit.ledger_governance_events (event_type, run_id, actor, approver, dual_control)
VALUES ('legal_hold_applied','gov-run-1','alice','bob',false);
INSERT INTO audit.ledger_governance_events (event_type, run_id, actor, approver, dual_control)
VALUES ('legal_hold_applied','gov-run-1','alice','bob',true);
INSERT INTO audit.ledger_governance_events (event_type, run_id, actor, approver, dual_control)
VALUES ('purge_completed','gov-run-1','alice','bob',true);
UPDATE audit.ledger_governance_events SET actor='mallory';
DELETE FROM audit.ledger_governance_events;
SELECT count(*) AS governance_rows FROM audit.ledger_governance_events;
SELECT has_table_privilege('manifest_writer','audit.run_manifests','UPDATE') AS writer_update_priv;
SELECT has_table_privilege('manifest_reader','audit.run_manifests','INSERT') AS reader_insert_priv;
