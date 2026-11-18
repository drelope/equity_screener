-- SYNTHETIC BACKFILL FIXTURE: NOT APPROVED, NOT PRODUCTION EVIDENCE.
-- Loads only on a disposable database after V0107–V0110 have been applied.
-- Every identity, timestamp, and source reference below is invented for rehearsal.
-- It exists to exercise the read-only readiness checks and cutover dry-run, not to
-- establish source mappings, status taxonomy, feed precedence, or approvals.

BEGIN;

INSERT INTO raw.company_ticker (ticker, cik, title, source_url, raw_payload)
VALUES
    ('SYN-A', '900000001', 'Synthetic Active A', 'synthetic', jsonb_build_object('synthetic', true)),
    ('SYN-B', '900000002', 'Synthetic Active B', 'synthetic', jsonb_build_object('synthetic', true)),
    ('SYN-C', '900000003', 'Synthetic Delisted C', 'synthetic', jsonb_build_object('synthetic', true))
ON CONFLICT (ticker, cik) DO NOTHING;

INSERT INTO reference.securities
    (ticker, cik, security_id, security_name, security_type, active, historical)
VALUES
    ('SYN-A', '900000001', '11111111-1111-4111-8111-111111111111', 'Synthetic Active A', 'common_stock', TRUE, FALSE),
    ('SYN-B', '900000002', '22222222-2222-4222-8222-222222222222', 'Synthetic Active B', 'common_stock', TRUE, FALSE),
    ('SYN-C', '900000003', '33333333-3333-4333-8333-333333333333', 'Synthetic Delisted C', 'common_stock', FALSE, TRUE)
ON CONFLICT (security_id) DO NOTHING;

-- V0107 RM-01: non-overlapping intervals, one delisted security with a closing date,
-- and a small as-of eligibility cache.
INSERT INTO reference.security_membership_history
    (security_id, status, effective_from, effective_to, listed_date, delisted_date, source, source_ref, run_id)
VALUES
    ('11111111-1111-4111-8111-111111111111', 'listed', '2024-01-01', NULL, '2024-01-01', NULL, 'synthetic', 'syn-mem-a1', 'synthetic-backfill-2026-11-16'),
    ('22222222-2222-4222-8222-222222222222', 'listed', '2024-01-01', NULL, '2024-01-01', NULL, 'synthetic', 'syn-mem-b1', 'synthetic-backfill-2026-11-16'),
    ('33333333-3333-4333-8333-333333333333', 'listed', '2024-01-01', '2025-06-30', '2024-01-01', '2025-06-30', 'synthetic', 'syn-mem-c1', 'synthetic-backfill-2026-11-16')
ON CONFLICT DO NOTHING;

UPDATE reference.securities
SET delisted_date = '2025-06-30'
WHERE security_id = '33333333-3333-4333-8333-333333333333';

INSERT INTO reference.security_eligibility_asof
    (as_of_date, security_id, is_eligible, eligibility_reason, source_run_id)
VALUES
    ('2026-11-09', '11111111-1111-4111-8111-111111111111', TRUE, 'synthetic active', 'synthetic-backfill-2026-11-16'),
    ('2026-11-09', '22222222-2222-4222-8222-222222222222', TRUE, 'synthetic active', 'synthetic-backfill-2026-11-16'),
    ('2026-11-09', '33333333-3333-4333-8333-333333333333', FALSE, 'synthetic delisted 2025-06-30', 'synthetic-backfill-2026-11-16')
ON CONFLICT (as_of_date, security_id) DO NOTHING;

-- V0108 RM-02: known-at timestamps precede availability and retrieval; no row has
-- availability before its ex-date.
INSERT INTO raw.dividend_data
    (security_id, ex_dividend_date, declaration_date, record_date, payment_date,
     amount, adjusted_amount, frequency, currency, provider, retrieved_at,
     declared_known_at, record_known_at, payment_known_at, ex_known_at,
     available_at, timing_evidence_source, timing_confidence)
VALUES
    ('11111111-1111-4111-8111-111111111111', '2026-03-13', '2026-02-20', '2026-03-16', '2026-03-31',
     0.50, 0.50, 'Quarterly', 'USD', 'synthetic-provider', '2026-02-21T12:00:00+00',
     '2026-02-20T12:00:00+00', '2026-02-21T12:00:00+00', '2026-02-21T12:00:00+00', '2026-02-21T12:00:00+00',
     '2026-03-14T00:00:00+00', 'synthetic-declaration-payload', 'high'),
    ('22222222-2222-4222-8222-222222222222', '2026-06-12', '2026-05-15', '2026-06-15', '2026-06-30',
     0.75, 0.75, 'Quarterly', 'USD', 'synthetic-provider', '2026-05-16T12:00:00+00',
     '2026-05-15T12:00:00+00', '2026-05-16T12:00:00+00', '2026-05-16T12:00:00+00', '2026-05-16T12:00:00+00',
     '2026-06-13T00:00:00+00', 'synthetic-declaration-payload', 'high')
ON CONFLICT (security_id, ex_dividend_date, provider) DO NOTHING;

-- V0109 RM-03: one evidence row per source event, one quarantined row with a reason,
-- and one linked correction. No duplicate provider/feed/source_event_key groups.
-- Guard by source-event key so repeated loads stay idempotent on fixtures without
-- a uniqueness constraint.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM raw.dividend_data_evidence WHERE source_event_key = 'SYN-A-2026Q1') THEN
        INSERT INTO raw.dividend_data_evidence
            (security_id, provider, feed, ex_dividend_date, declaration_date, record_date,
             payment_date, amount, adjusted_amount, amount_feed, currency, frequency,
             source_event_key, source_payload_hash, source_payload, retrieved_at,
             ingest_run_id, is_quarantined, quarantine_reason)
        VALUES
            ('11111111-1111-4111-8111-111111111111', 'synthetic-provider', 'primary', '2026-03-13', '2026-02-20', '2026-03-16',
             '2026-03-31', 0.50, 0.50, 'declared', 'USD', 'Quarterly',
             'SYN-A-2026Q1', 'hash-syn-a-q1', jsonb_build_object('synthetic', true, 'event', 'A-Q1'), '2026-02-22T00:00:00+00',
             'synthetic-backfill-2026-11-16', FALSE, NULL),
            ('22222222-2222-4222-8222-222222222222', 'synthetic-provider', 'primary', '2026-06-12', '2026-05-15', '2026-06-15',
             '2026-06-30', 0.75, 0.75, 'declared', 'USD', 'Quarterly',
             'SYN-B-2026Q2', 'hash-syn-b-q2', jsonb_build_object('synthetic', true, 'event', 'B-Q2'), '2026-05-17T00:00:00+00',
             'synthetic-backfill-2026-11-16', FALSE, NULL),
            ('22222222-2222-4222-8222-222222222222', 'synthetic-provider', 'secondary', '2026-06-12', '2026-05-15', '2026-06-15',
             '2026-06-30', 7.50, 7.50, 'declared', 'USD', 'Quarterly',
             'SYN-B-2026Q2-SECONDARY', 'hash-syn-b-q2-bad', jsonb_build_object('synthetic', true, 'event', 'B-Q2-bad'), '2026-05-18T00:00:00+00',
             'synthetic-backfill-2026-11-16', TRUE, 'implausible_amount')
        ON CONFLICT DO NOTHING;

        INSERT INTO audit.dividend_quarantine
            (evidence_id, security_id, provider, feed, reason_code, reason_detail, row_snapshot, status, detected_by_run_id)
        SELECT
            e.evidence_id, e.security_id, e.provider, e.feed,
            'implausible_amount', 'synthetic amount 7.50 vs expected 0.75',
            to_jsonb(e), 'open', 'synthetic-backfill-2026-11-16'
        FROM raw.dividend_data_evidence e
        WHERE e.source_event_key = 'SYN-B-2026Q2-SECONDARY';

        INSERT INTO audit.dividend_corrections
            (security_id, provider, feed, target_event_key, field_name, old_value, new_value,
             correction_reason, source_evidence_id, approved_by, run_id)
        SELECT
            e.security_id, e.provider, e.feed, e.source_event_key, 'amount', '7.50', '0.75',
            'synthetic secondary-feed conflict resolved to primary', e.evidence_id,
            'synthetic-approver', 'synthetic-backfill-2026-11-16'
        FROM raw.dividend_data_evidence e
        WHERE e.source_event_key = 'SYN-B-2026Q2';


    END IF;
END;
$$;

-- V0110 RM-04/05: one ledger manifest and one output ref for the synthetic run.
INSERT INTO audit.run_manifests
    (run_id, run_type, created_at_utc, parameters, input_refs, output_refs, environment,
     status, manifest_hash, manifest_json, recorded_by)
VALUES
    ('synthetic-backfill-2026-11-16', 'backfill', '2026-11-16T00:00:00+00',
     '{}'::jsonb, '{"fixture":"synthetic-backfill-2026-11-16.sql"}'::jsonb,
     '{"evidence_rows":3}'::jsonb, '{"environment":"disposable-rehearsal"}'::jsonb,
     'created', '0000000000000000000000000000000000000000000000000000000000000000',
     '{"run_id":"synthetic-backfill-2026-11-16","run_type":"backfill"}'::jsonb,
     'synthetic-rehearsal')
ON CONFLICT (run_id) DO NOTHING;

INSERT INTO audit.run_outputs
    (run_id, output_kind, entity_type, entity_id, storage_ref, content_hash, created_at_utc, metadata)
VALUES
    ('synthetic-backfill-2026-11-16', 'backfill_report', NULL, NULL,
     'synthetic://artifacts/synthetic-backfill-2026-11-16.json', 'synthetic-hash',
     '2026-11-16T00:00:00+00', jsonb_build_object('synthetic', true))
ON CONFLICT (run_id, output_kind, storage_ref) DO NOTHING;

COMMIT;
