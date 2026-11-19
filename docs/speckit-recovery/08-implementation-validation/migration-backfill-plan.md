# Migration & Backfill Plan (P0)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Schema/data changes for `RM-01..05` (PIT membership, timing fields, adjustment/dividend evidence, manifests/reports) |
| Safety | Backwards-aware, auditable migrations; no destructive loss of historical evidence; reversible where feasible; isolated validation before shared deployment |

## 1. Principles
- Additive-first migrations where possible (new tables/columns/views), then dual-write/backfill, then consumer cutover, then constrained cleanup only after verification.
- All migrations versioned in canonical migration path per `DEC-007`; ledger reconciled and recorded.
- Every backfill/recompute emits a manifest/run record (`run_id`, inputs, code SHA, timestamps, counts, checksums).

## 2. Migration sequence

| Seq | WP | Change | Notes / rollback |
|---|---|---|---|
| M1 | WP1 | PIT membership/status history structures; `delisted_date` population strategy; indexes for `as_of` queries | Additive tables/columns; rollback by dropping new unused structures/views after cutover abort |
| M2 | WP2 | Filing/acceptance/availability timestamp fields for fundamentals; dividend known-as-of/support fields as needed | Additive; backfill from source payloads/filings where available; nullability explicit |
| M3 | WP3a | Dividend evidence retention model (append-only evidence and/or key redesign) + audit/quarantine/correction tables | Preserve existing `raw.dividend_data`; dual-write/copy evidence before changing uniqueness semantics |
| M4 | WP3b | Market adjustment representation (raw/adjusted/basis metadata) | Add columns/tables/views; backfill adjusted series deterministically with recorded policy version |
| M5 | WP4/5 | Manifest/provenance and report/score versioning storage | Additive, append-only; ensure immutability constraints/triggers/policies as designed |
| M6 | WP3-5 | Constraints/indexes/consumer views after validation | Apply tightening constraints only after data quality checks pass |

## 3. Backfill & recompute strategy

| Area | Strategy | Validation |
|---|---|---|
| PIT membership | Load historical status/listing/delist evidence; derive `eligible_as_of`; populate `delisted_date` where authoritative | Counts by `as_of`, spot checks, inactive security coverage, reproducibility |
| Fundamentals availability | Backfill `filed/accepted/available_at` from SEC/source metadata; recompute PIT feature views/snapshots | Leak tests, before/after availability comparisons |
| Dividend evidence | Preserve all existing rows; ingest/backfill feed/source/provenance; build curated projection with deterministic precedence | Row-count reconciliation, key-collision audit, basis/date completeness metrics |
| Adjusted prices/returns | Compute or ingest adjusted series per approved policy from corporate actions/provider evidence; version policy | Split/dividend golden cases, continuity, total-return reconciliation |
| Scores/reports | Recompute run-keyed outputs as needed; retain prior outputs for audit comparison | Manifest linkage, hash/diff checks, `UNK-003` delta after RM-01 |

## 4. Data quality gates (pre/post)
- No unintended row loss for raw/evidence sources (count/hash reconciliation by partition/source).
- PK/unique changes validated on copy in isolated DB before production migration.
- Null/invalid date rates and adjustment anomalies measured and reviewed.
- Dedupe/quarantine/correction counts recorded and explainable.

## 5. Rollback and contingency
- Keep old columns/tables readable until new consumers verified; use views for cutover where possible.
- Rollback = revert consumers/views to prior path; do not delete evidence tables/backups during stabilization window.
- If backfill quality fails gates, stop cutover, retain new additive structures for diagnosis, and record incident in execution log/decision tracker.

## 6. Approvals required before production cutover
- M1/M2 decisions recorded (`EX-*`, `DEC-*`, especially basis/lock/policy decisions).
- Isolated migration + backfill + validation evidence attached.
- DBA/owner sign-off for backup/restore readiness and maintenance window (external evidence, `UNK-007`).


## 7. Draft artifacts (2026-11-16, non-applied)

Additive SQL drafts created under `docs/speckit-recovery/08-implementation-validation/sql-drafts/` (kept out of `sql/migrations/` until approved/numbered/validated):

| Draft | Covers | Status |
|---|---|---|
| `sql-drafts/rm01_pit_membership_additive.sql` | M1/RM-01 membership history, eligibility scaffold, `delisted_date` | Draft |
| `sql-drafts/rm02_pit_timing_additive.sql` | M2/RM-02 filing/acceptance/available and dividend known-as-of timing fields | Draft |
| `sql-drafts/rm03_dividend_evidence_quarantine.sql` | M3/RM-03 append-only dividend evidence, quarantine, corrections | Draft |
| `sql-drafts/rm04_run_manifest_ledger.sql` | M5/RM-04/05 immutable run manifest ledger, run-keyed output refs | Draft |

Promotion path: DEC/UNK approvals -> isolated migration rehearsal (disposable DB) -> backfill/reconciliation scripts + manifests -> consumer cutover/dual-read -> constraint tightening. No shared DB application performed.

### 7.1 Numbered migration candidates (2026-11-16, non-applied)

Numbered candidates derived from the drafts live under `sql-candidates/`, deliberately **outside** `sql/migrations/` so the migrator cannot discover them. They start at **V0107** after the current on-disk maximum **V0106**; the historical **V0045** gap is not reused (UNK-006 rationale still undocumented).

| Candidate | Area | Backfill | Rollback | Approval gates |
|---|---|---|---|---|
| `sql-candidates/V0107_rm01_pit_membership.sql` | RM-01 | Required (membership, delisted_date, eligibility cache) | `sql-candidates/rollback/V0107_rollback.sql` | M1, EX-001, EX-004, UNK-003 |
| `sql-candidates/V0108_rm02_pit_timing.sql` | RM-02 | Required (known-at/available_at; fundamentals ALTERs disabled) | `sql-candidates/rollback/V0108_rollback.sql` | M1, EX-003, UNK-001, UNK-002 |
| `sql-candidates/V0109_rm03_dividend_evidence.sql` | RM-03 | Required (evidence/quarantine backfill, dual-read) | `sql-candidates/rollback/V0109_rollback.sql` | M1, EX-002, UNK-002, UNK-005 |
| `sql-candidates/V0110_rm04_run_manifest_ledger.sql` | RM-04/05 | Not required for DDL; optional historical manifest backfill | `sql-candidates/rollback/V0110_rollback.sql` | M1, DEC-002, DEC-003, DEC-005 |
| `sql-candidates/V0111_rm04_manifest_immutability.sql` | RM-04 | Not required | `sql-candidates/rollback/V0111_rollback.sql` | M1, DEC-002, DEC-003, DEC-005 |

Dependency/backfill/rollback details: `sql-candidates/dependency-and-rollback-notes.md`. Candidate manifest/hashes: `sql-candidates/candidate-manifest.json`. Static consistency check: `python3 scripts/check_migration_candidates.py` (validates numbering, hashes, headers, additive-only SQL, dependencies, rollback-file presence; it does **not** approve or apply).

Candidate apply/rollback DDL rehearsal (2026-11-16, isolated disposable `postgres:17-alpine`, created/destroyed): all four candidates applied after the canonical baseline, target objects verified present, rollback scripts applied in reverse order, candidate objects verified absent, `public.schema_migrations` intact. Evidence: `sql-candidates/rehearsal-apply-rollback-2026-11-16.json`. Caveats: DDL-only, no backfill/cutover/performance/approval, and manual ledger deletions were not exercised. Promotion still requires a fresh rehearsal with approved backfill/cutover evidence.

### 7.2 Candidate backfill/reconciliation readiness (2026-11-16, read-only)

Backfill readiness is a separate gate from DDL compatibility. `sql-candidates/backfill/` defines read-only diagnostics for V0107–V0110; no backfill SQL is committed yet because source mappings, status taxonomy, feed/precedence, and cutover rules remain approval-gated.

```bash
# static checks only (no DB)
python3 scripts/check_candidate_backfill_readiness.py

# read-only checks on an isolated/approved target
python3 scripts/check_candidate_backfill_readiness.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:<port>/rehearsal' \
  --json-out docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/readiness-<date>.json
```

The tool refuses non-local hosts/shared-like database names unless explicitly allowed, opens a **READ ONLY** transaction, and reports per-candidate coverage/anomalies: V0107 membership/delisted/overlap; V0108 availability/known-at coverage and timing anomalies; V0109 evidence/quarantine/correction linkage and duplicate source events; V0110 manifest hash/JSON and output storage/content-hash gaps. Exit `0` = checks passed, `1` = schema missing/backfill incomplete/anomaly, `2` = safety/DB/usage error.

Read-only demonstration (2026-11-16, isolated disposable `postgres:17-alpine` 127.0.0.1:55440, created/destroyed): V0107–V0110 applied to the canonical baseline, all candidate schemas present, no backfill data seeded. Result: `not_ready_no_backfill_data` (exit 1, expected), proving the checks execute and fail closed. Evidence: `sql-candidates/backfill/rehearsal-schema-apply-2026-11-16.json`, `sql-candidates/backfill/readiness-2026-11-16.json`. Caveats: no approved/synthetic backfill data was loaded; no cutover/performance/approval; this is **not** promotion evidence.

### 7.3 Manifest ledger persistence scaffolding (2026-11-16, opt-in)

`src/crispdm/manifest_store.py` + `scripts/persist_run_manifest.py` provide an
opt-in persistence path for `audit.run_manifests`/`audit.run_outputs` (V0110).
Default is dry-run; writes require `--persist --i-understand-ledger-write` and an
isolated/approved DSN. The path never creates tables, never updates rows, treats an
identical `run_id`/hash rerun as a no-op, and raises on a hash conflict.

Integration on isolated disposable Postgres (`127.0.0.1:55441/rehearsal`,
created/destroyed; no shared DB): baseline + V0107–V0110 applied; one manifest +
one output persisted; identical rerun was idempotent; changed payload under the same
`run_id` exited 1. Readback confirmed one manifest row and one output row. Evidence:
`sql-candidates/manifest-ledger-integration-2026-11-16.json`. Pipeline wiring,
immutability triggers/roles, retention, historical backfill, and run-keyed report
stores remain unimplemented and approval-gated.


### 7.4 Manifest immutability candidate (2026-11-16, non-applied)

`V0111_rm04_manifest_immutability.sql` adds the deferred append-only triggers for
V0110. On isolated disposable Postgres, `UPDATE`/`DELETE` on both ledger tables
raised SQLSTATE `23000` and left the inserted row unchanged; reverse rollback removed
the triggers/function and all candidate objects while `public.schema_migrations`
remained. Evidence: `sql-candidates/rehearsal-v0111-2026-11-16.json` (behavior) and
`sql-candidates/rehearsal-apply-rollback-v0111-2026-11-16.json` (full tool
apply/rollback, `status=applied_and_rolled_back`). Role/grants, retention,
incident-response exceptions, and pipeline wiring remain unimplemented and
approval-gated.

### 7.5 Manifest ledger governance policy (2026-11-16, draft)

`manifest-ledger-governance-policy-template.json` + `manifest-ledger-governance-policy-draft.md`
define the draft role/grant, retention, and incident-response invariants for the
V0110/V0111 ledger. `scripts/check_manifest_ledger_policy.py` enforces structural and
safety checks: writer has no `UPDATE`/`DELETE`/`TRUNCATE`, readers/auditors are
read-only, no `PUBLIC` grants, legal hold and purge approvals are required, and
break-glass is dual-control and separated from app roles.

The draft passes (`python3 scripts/check_manifest_ledger_policy.py`, exit 0);
`--require-approved` exits 1 because M1/DEC-002/003/005 evidence and a retention
period are missing. No role/grant SQL candidate, retention job, incident table, or
operational boundary test exists. Approvals remain required before promotion.

### 7.6 Synthetic backfill/cutover dry-run (2026-11-16, non-applied)

`sql-candidates/backfill/synthetic-backfill-2026-11-16.sql` plus
`scripts/rehearse_backfill_synthetic.py` provide a deterministic synthetic-data
rehearsal for V0107–V0110. On an isolated disposable Postgres after applying the
candidate DDL, the fixture loaded and the read-only readiness checker reported
`checks_passed` for every candidate (exit 0). Evidence:
`sql-candidates/backfill/synthetic-backfill-2026-11-16.json` and
`readiness-after-synthetic-synthetic-backfill-2026-11-16.json`. The cutover
sequence to repeat with approved data is in
`sql-candidates/backfill/synthetic-cutover-dry-run.md`. This is rehearsal only:
no source mapping, status taxonomy, feed precedence, dual-read, cutover, or
promotion is established.

### 7.7 Delisting and reclassification backfill rules (US1, 2026-11-18)

- Populate `reference.securities.delisted_date` only from authoritative listing/exchange/filing evidence or an explicitly approved conservative proxy. Record source, run ID, and decision reference with each backfill.
- Do not infer delisting from `active = FALSE`; current inactivity is not historical delisting evidence.
- Reclassification and identity release/merge must preserve closed membership intervals or tombstones. Historical rows are never deleted for cleanup.
- Membership intervals must be non-overlapping per security and reconciled before `reference.security_eligibility_asof` is treated as authoritative.
- Unknown delisting dates remain NULL and are reported by the readiness checker; NULL does not mean still listed.
- Until RM-01 membership backfill and survivor-vs-PIT comparison are approved, covered outputs retain survivor-biased, non-decision-grade labeling under EX-001/EX-004.
