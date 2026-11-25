# Run Manifest Ledger Persistence (Draft / Opt-In)

Status: **candidate-only, not approved, not wired into pipelines.** Requires
`V0110_rm04_run_manifest_ledger.sql` to exist on an approved target. This is
tooling/scaffolding for RM-04/RM-05, not promotion evidence.

## What Exists

- `src/crispdm/manifest_store.py`: validates/builds ledger rows, checks table
  availability, inserts manifests/output refs with `ON CONFLICT DO NOTHING`,
  and raises on a `run_id` hash conflict instead of overwriting.
- `scripts/persist_run_manifest.py`: CLI. Dry-run by default; actual write
  requires both `--persist` and `--i-understand-ledger-write`.
- `tests/test_manifest_store.py`: unit/dry-run/safety coverage.

## Append-Only Semantics

- Existing `run_id` with the same manifest hash: idempotent no-op.
- Existing `run_id` with a different hash: `ManifestConflictError`, exit 1.
- No `UPDATE`/`DELETE`/upsert mutation is issued.
- Output refs dedupe on `(run_id, output_kind, storage_ref)` and never update
  existing rows.
- The caller owns the transaction; the CLI uses `engine.begin()` and rolls back
  on error.

The database does not yet enforce immutability on an approved target: the V0111
trigger candidate exists and was rehearsed (`sql-candidates/rehearsal-v0111-2026-11-16.json`)
but is **not applied**. Role/grants and retention/incident-response policy depend on
DEC-002/DEC-003/DEC-005. Until then, append-only behavior is a code contract, not an
approved database guarantee.

## Usage

Dry-run (no database access):

```bash
python3 scripts/persist_run_manifest.py --manifest artifacts/runs/<run>/manifest.json --json
```

Opt-in write on an isolated/approved target only:

```bash
python3 scripts/persist_run_manifest.py \
  --manifest artifacts/runs/<run>/manifest.json \
  --outputs artifacts/runs/<run>/outputs.json \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:<port>/rehearsal' \
  --persist --i-understand-ledger-write --recorded-by <operator> \
  --json-out docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/<run>-persist.json
```

Safety: refuses non-local hosts and shared/production-like database names unless
explicitly overridden; never creates tables; treats missing ledger tables as an
error (exit 2).

## Integration Evidence (2026-11-16)

Isolated disposable `postgres:17-alpine` (127.0.0.1:55441/rehearsal,
created/destroyed; no shared/project DB touched):

1. Applied baseline + V0107–V0110 (`manifest-ledger-rehearsal-2026-11-16.json`).
2. Persisted one manifest + one output ref: insert succeeded.
3. Reran identical payload: manifest/output no-ops (idempotent).
4. Reran with changed parameters under the same `run_id`: exit 1 conflict.
5. Readback: one `audit.run_manifests` row, one `audit.run_outputs` row.

Evidence: `sql-candidates/manifest-ledger-integration-2026-11-16.json`,
`sql-candidates/backfill/manifest-ledger-persist-2026-11-16.json`.

## Read Path (candidate)

`src/crispdm/manifest_store.py` exposes `get_run_manifest`, `get_run_outputs`, and
`get_run_bundle` (SELECT-only, no commits). `scripts/show_run_ledger.py` wraps the
bundle read in an explicit `SET TRANSACTION READ ONLY`, refuses shared-like targets
by default, and returns exit 0 (found), 1 (missing run_id), or 2 (safety/DB/ledger
error). It emits sanitized target metadata and never writes evidence to the DB.

Disposable Postgres rehearsal (2026-11-16, port 55444, destroyed): applied
V0107–V0111, persisted one manifest + one output, read the bundle back with
`output_count=1`, and got exit 1 for a missing run. Evidence:
`sql-candidates/backfill/run-ledger-read-2026-11-16.json`. This proves the read
path only; role enforcement and retention/incident handling remain unimplemented.

An additional read-only check, `scripts/check_manifest_ledger_integrity.py`, recomputes
`manifest_hash` from `manifest_json`, compares denormalized columns, validates row
keys/status, and detects orphan outputs. On the same disposable pattern (port 55445,
destroyed) a valid ledger passed with 1 run/1 output/0 issues; a deliberately bad
appended manifest was detected (exit 1, hash mismatch). Evidence:
`sql-candidates/backfill/run-ledger-integrity-2026-11-16.json` and
`run-ledger-integrity-detects-bad-2026-11-16.json`. Detection is not repair or
enforcement.

## Governance

Role/grant, retention, and incident-response invariants are drafted in
`manifest-ledger-governance-policy-draft.md` and validated by
`scripts/check_manifest_ledger_policy.py`. The draft passes structural/safety checks;
`--require-approved` fails because approvals/retention are pending. No grants,
retention jobs, or incident tables are implemented.

## Not Done / Blocked

- No automatic persistence wiring in `score_rank.py`, `backtest.py`, or other
  scripts; that waits for approval and dual-write/cutover design.
- V0111 trigger candidate exists but is not applied; no role/grant model or
  retention/incident-response policy.
- No historical manifest backfill, no run-keyed report/score store, no
  load/performance/concurrency evidence.
- DEC-002/003/005 and M1 remain pending; `V0110` remains outside
  `sql/migrations/`.
