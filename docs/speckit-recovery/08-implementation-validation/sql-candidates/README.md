# Numbered Migration Candidates (Not Applied)

Numbered, promotion-ready **candidates** derived from `../sql-drafts/`. They are intentionally kept under this recovery package, not in `sql/migrations/`, so `scripts/migrate.py` cannot discover or apply them.

| Candidate | Area | Purpose | Approval gates | Backfill | Rollback |
|---|---|---|---|---|---|
| `V0107_rm01_pit_membership.sql` | RM-01 | Membership/status history, as-of eligibility scaffold, `reference.securities.delisted_date` | M1, EX-001, EX-004, UNK-003 | Required | `rollback/V0107_rollback.sql` |
| `V0108_rm02_pit_timing.sql` | RM-02 | Dividend known-as-of timing columns and availability indexes | M1, EX-003, UNK-001, UNK-002 | Required | `rollback/V0108_rollback.sql` |
| `V0109_rm03_dividend_evidence.sql` | RM-03 | Append-only dividend evidence, quarantine, corrections | M1, EX-002, UNK-002, UNK-005 | Required | `rollback/V0109_rollback.sql` |
| `V0110_rm04_run_manifest_ledger.sql` | RM-04/05 | Run manifest ledger and run-keyed output refs (trigger deferred) | M1, DEC-002, DEC-003, DEC-005 | Not required (new tables) | `rollback/V0110_rollback.sql` |
| `V0111_rm04_manifest_immutability.sql` | RM-04 | Append-only triggers for V0110 manifests/outputs | M1, DEC-002, DEC-003, DEC-005 | Not required | `rollback/V0111_rollback.sql` |

## Numbering policy

- Current on-disk migration maximum is **V0106**; candidates start at **V0107**.
- The historical **V0045** gap is never reused. UNK-006 resolved the ledger/file mismatch but the gap rationale remains undocumented; reusing it would rewrite history.
- Candidate versions must stay unique, collision-free with `sql/migrations/`, and above the current maximum. `scripts/check_migration_candidates.py` enforces this.
- Renumbering after an approval conflict is a deliberate, reviewed operation: update the filename, `candidate-manifest.json`, this table, and rerun the checker. Do not silently shift versions.

## Dependency and promotion order

```
V0107 (RM-01 membership)  ──soft──▶ UNK-003 post-implementation comparison
V0108 (RM-02 timing)      ──soft──▶ V0109 evidence known-as-of cutover
V0109 (RM-03 evidence)    ──soft──▶ RM-03 loader/dual-read/cutover
V0110 (RM-04/05 ledger)   ──hard──▶ V0111 append-only triggers
V0111 (RM-04 guard)       ──soft──▶ RM-05 run-keyed outputs/reports
```

Hard DDL dependencies: none among the four candidates (each targets existing schemas/tables). Soft dependencies are data/cutover dependencies, not apply-order blockers.

## Promotion checklist (all required)

1. Record approvals in `../../06-execution-prep/m1-decision-log-template.md` and `decision-unknown-tracker.md` (M1, EX/DEC/UNK gates per candidate).
2. Confirm numbering against the live ledger (`public.schema_migrations`) and repo `sql/migrations/`; resolve any new conflict before promoting.
3. Rehearse on an **isolated disposable** database with the canonical baseline (see `../sql-drafts/rehearsal-notes.md`), then record hashes/evidence.
4. Write and validate backfill/reconciliation scripts; do not backfill in the migration itself.
5. Validate rollback on a disposable copy with representative data, including the manual `schema_migrations` ledger deletion step.
6. Update the checker manifest if any SQL or version changes; rerun `python3 scripts/check_migration_candidates.py`.
7. Only then move files to `sql/migrations/` (single underscore filename, matching migrator regex), and add the ledger/backfill evidence to the execution log.

## Validation

```bash
python3 scripts/check_migration_candidates.py
python3 scripts/check_migration_candidates.py --json
PYTHONPATH=. python3 -m pytest tests/test_check_migration_candidates.py -q
```

The checker validates internal consistency only. **PASS does not mean approved, applied, verified, or promotion-grade.**

## Disposable rehearsal evidence (2026-11-16)

Applied and rolled back all four numbered candidates on an isolated `postgres:17-alpine` database (created/destroyed by the agent; no shared/project DB touched):

```bash
python3 scripts/rehearse_p0_full.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:<port>/rehearsal' \
  --drafts-dir docs/speckit-recovery/08-implementation-validation/sql-candidates \
  --rollback --apply --verify --i-understand-disposable-target \
  --out docs/speckit-recovery/08-implementation-validation/sql-candidates/rehearsal-apply-rollback-2026-11-16.json
```

Result: `status=applied_and_rolled_back`; all nine target objects/columns verified present after apply; all eight candidate objects/columns absent after rollback; `public.schema_migrations` remained. Evidence: `rehearsal-apply-rollback-2026-11-16.json`.

Caveats: DDL-only rehearsal (no backfill, data reconciliation, consumer cutover, performance/load, or approval). Rollback scripts are destructive and were exercised only against a disposable copy; the manual `schema_migrations` ledger deletions were **not** performed in rehearsal (the baseline ledger is shared with the project's migration history and is intentionally left intact on disposable runs). Promotion still requires fresh rehearsal with final numbered files and approved backfill/cutover evidence.


## V0111 immutability rehearsal (2026-11-16)

Applied V0107–V0111 on isolated disposable Postgres, persisted one manifest/output pair, and verified `UPDATE`/`DELETE` on both ledger tables fail with SQLSTATE `23000`; rows remained unchanged. Reverse rollback removed both triggers and all candidate objects while `public.schema_migrations` remained. Evidence: `rehearsal-v0111-2026-11-16.json` (behavior + manual rollback), `rehearsal-apply-rollback-v0111-2026-11-16.json` (full tool apply/rollback, `status=applied_and_rolled_back`), and `rehearsal-v0111-apply-2026-11-16.json`.

Caveats: trigger-only guard; no role/grant/retention/incident-response model; empty-ledger rollback only; no approval. The V0111 candidate remains outside `sql/migrations/`.

## Backfill/reconciliation readiness (read-only)

`backfill/README.md` documents the backfill gate; `backfill/readiness_checks.sql` is the generated DBA review catalog; `scripts/check_candidate_backfill_readiness.py` is the canonical checker. Static checks pass, and a read-only run against an isolated disposable database with V0107–V0110 applied (no seeded data) reported `not_ready_no_backfill_data` as expected. Evidence: `backfill/rehearsal-schema-apply-2026-11-16.json`, `backfill/readiness-2026-11-16.json`.

```bash
python3 scripts/check_candidate_backfill_readiness.py
python3 scripts/check_candidate_backfill_readiness.py --dsn '<isolated-read-only-dsn>' --json-out <report.json>
```

The checker does not backfill, mutate, approve, or promote. No backfill SQL is committed until the approval gates in `backfill/README.md` are met.

## Manifest ledger persistence (opt-in, 2026-11-16)

`src/crispdm/manifest_store.py` and `scripts/persist_run_manifest.py` provide an
opt-in writer for the V0110 ledger. Dry-run is the default; actual writes require
`--persist --i-understand-ledger-write` and an isolated/approved DSN. The writer
does not create tables or update rows, no-ops identical `run_id`/hash reruns, and
refuses a changed payload for an existing `run_id`.

Integration evidence on isolated disposable Postgres: insert + output ref, idempotent
rerun, and conflict refusal all behaved as intended. Evidence:
`manifest-ledger-integration-2026-11-16.json`; design: `../manifest-ledger-persistence-draft.md`.
No pipeline is wired automatically; the draft role/grant/retention/incident-response
policy is in `../manifest-ledger-governance-policy-draft.md` and still approval-gated.
A read-only run-keyed lookup is available via `scripts/show_run_ledger.py`; its
rehearsal evidence is `backfill/run-ledger-read-2026-11-16.json`. Read-only hash/
column/orphan checks are in `scripts/check_manifest_ledger_integrity.py` with
evidence at `backfill/run-ledger-integrity-2026-11-16.json` and
`backfill/run-ledger-integrity-detects-bad-2026-11-16.json`.

Speculative (non-applied) additions: `V0112_rm04_ledger_role_grants.sql` (least-privilege
grants on the ledger; requires DBA-provisioned NOLOGIN NOINHERIT roles) and
`V0113_rm04_ledger_governance_events.sql` (append-only governance event log for
holds, exports, purges, incidents, and break-glass). Both are approval-gated (M1,
DEC-002/003/005). Rehearsal evidence is in this directory: `ledger-roles-events-apply-rollback-2026-11-16.json`,
`ledger-governance-behavior-2026-11-16.sql`, and the `ledger-*-rehearsal-*.json` files.
