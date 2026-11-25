-- CANDIDATE BACKFILL READINESS CHECKS: READ-ONLY / NOT APPLIED
-- Generated from scripts/check_candidate_backfill_readiness.py.
-- Run inside a READ ONLY transaction against an approved target only.

-- V0107: RM-01 PIT membership (primary count: membership_rows)
-- check: membership_rows
SELECT count(*) FROM reference.security_membership_history;

-- check: securities_total
SELECT count(*) FROM reference.securities;

-- check: securities_with_delisted_date
SELECT count(*) FROM reference.securities WHERE delisted_date IS NOT NULL;

-- check: inactive_securities
SELECT count(*) FROM reference.securities WHERE active IS FALSE;

-- check: inactive_without_delisted_date
-- issue when positive: inactive securities without delisted_date (backfill incomplete or unknown)
SELECT count(*) FROM reference.securities WHERE active IS FALSE AND delisted_date IS NULL;

-- check: open_membership_intervals
SELECT count(*) FROM reference.security_membership_history WHERE effective_to IS NULL;

-- check: overlapping_membership_pairs
-- issue when positive: overlapping membership intervals
SELECT count(*) FROM (
                  SELECT security_id, effective_from, effective_to,
                         LAG(effective_to) OVER (
                           PARTITION BY security_id ORDER BY effective_from
                         ) AS prev_to,
                         ROW_NUMBER() OVER (
                           PARTITION BY security_id ORDER BY effective_from
                         ) AS rn
                  FROM reference.security_membership_history
                ) t
                WHERE rn > 1 AND (prev_to IS NULL OR effective_from <= prev_to);

-- check: eligibility_rows
SELECT count(*) FROM reference.security_eligibility_asof;

-- V0108: RM-02 PIT timing (primary count: dividend_rows)
-- check: dividend_rows
SELECT count(*) FROM raw.dividend_data;

-- check: rows_with_available_at
SELECT count(*) FROM raw.dividend_data WHERE available_at IS NOT NULL;

-- check: rows_with_ex_known_at
SELECT count(*) FROM raw.dividend_data WHERE ex_known_at IS NOT NULL;

-- check: rows_with_any_known_at
SELECT count(*) FROM raw.dividend_data WHERE declared_known_at IS NOT NULL OR record_known_at IS NOT NULL OR payment_known_at IS NOT NULL OR ex_known_at IS NOT NULL;

-- check: available_before_ex_date
-- issue when positive: availability timestamp precedes the ex-dividend date
SELECT count(*) FROM raw.dividend_data WHERE available_at IS NOT NULL AND ex_dividend_date IS NOT NULL AND available_at::date < ex_dividend_date;

-- check: available_without_evidence_source
-- issue when positive: availability rows missing timing_evidence_source
SELECT count(*) FROM raw.dividend_data WHERE available_at IS NOT NULL AND timing_evidence_source IS NULL;

-- check: known_at_after_retrieval
-- issue when positive: ex_known_at later than retrieval time
SELECT count(*) FROM raw.dividend_data WHERE ex_known_at IS NOT NULL AND ex_known_at > retrieved_at;

-- check: no_availability_backfill
-- issue when all_rows: no available_at backfill (all dividend rows NULL)
SELECT count(*) FROM raw.dividend_data WHERE available_at IS NULL;

-- V0109: RM-03 dividend evidence/quarantine (primary count: evidence_rows)
-- check: evidence_rows
SELECT count(*) FROM raw.dividend_data_evidence;

-- check: raw_dividend_rows
SELECT count(*) FROM raw.dividend_data;

-- check: quarantined_evidence_rows
SELECT count(*) FROM raw.dividend_data_evidence WHERE is_quarantined IS TRUE;

-- check: open_quarantine_rows
SELECT count(*) FROM audit.dividend_quarantine WHERE status = 'open';

-- check: quarantine_without_evidence
-- issue when positive: quarantine rows without evidence linkage (legacy rows need review)
SELECT count(*) FROM audit.dividend_quarantine WHERE evidence_id IS NULL;

-- check: correction_rows
SELECT count(*) FROM audit.dividend_corrections;

-- check: corrections_without_evidence
-- issue when positive: correction rows without source evidence linkage
SELECT count(*) FROM audit.dividend_corrections WHERE source_evidence_id IS NULL;

-- check: duplicate_source_event_groups
-- issue when positive: duplicate provider/feed/source_event_key evidence groups
SELECT count(*) FROM (
                  SELECT provider, feed, source_event_key
                  FROM raw.dividend_data_evidence
                  WHERE source_event_key IS NOT NULL
                  GROUP BY provider, feed, source_event_key
                  HAVING count(*) > 1
                ) d;

-- V0110: RM-04/RM-05 run manifest ledger (primary count: manifest_rows)
-- check: manifest_rows
SELECT count(*) FROM audit.run_manifests;

-- check: output_rows
SELECT count(*) FROM audit.run_outputs;

-- check: manifests_missing_hash
-- issue when positive: run manifests missing manifest_hash
SELECT count(*) FROM audit.run_manifests WHERE manifest_hash IS NULL OR manifest_hash = '';

-- check: manifests_missing_json
-- issue when positive: run manifests missing manifest_json
SELECT count(*) FROM audit.run_manifests WHERE manifest_json IS NULL;

-- check: outputs_without_storage_ref
-- issue when positive: run outputs missing storage_ref
SELECT count(*) FROM audit.run_outputs WHERE storage_ref IS NULL OR storage_ref = '';

-- check: outputs_without_content_hash
SELECT count(*) FROM audit.run_outputs WHERE content_hash IS NULL;
