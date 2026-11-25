# US2 Verification: Defensible Decision Evidence

**Feature**: `specs/001-p0-recovery/spec.md`

**Scope**: T016–T022 (P1)

**Status**: Scaffolding and policies verified; production wiring and role enforcement remain approval-gated

## T016 — Manifest conflict/idempotency

- `src/crispdm/manifest_store.py` builds canonical manifest rows, checks ledger availability, inserts with `ON CONFLICT DO NOTHING`, treats identical hash reruns as no-ops, and raises `ManifestConflictError` for the same `run_id` with a different hash.
- Verified with `tests/test_manifest_store.py`: 15 tests pass.

## T017 — No-overwrite output storage

- `src/crispdm/output_store.py` stores `<run_id>/<output_kind>.json`, rejects unsafe path components, computes canonical content hashes, treats identical payloads as no-ops, and raises `OutputConflictError` for differing payloads.
- Verified with `tests/test_output_store.py`: 7 tests pass.

## T018 — Opt-in persistence wiring

- `scripts/persist_run_manifest.py` and `scripts/persist_run_output.py` remain standalone explicit opt-in CLIs.
- No automatic persistence was wired into `scripts/score_rank.py`, `scripts/backtest.py`, or `scripts/evaluate_walk_forward.py` at this checkpoint.
- DEC-002/003/005 outcomes are recorded with evidence due 2026-12-15; ledger cutover requires complete evidence and approval.

## T019 — Append-only DDL/rollback rehearsal

- `scripts/rehearse_p0_full.py --check-only` verifies V0110/V0111 candidates and rollbacks: 7 candidates checked, exit 0.
- Prior isolated rehearsals: `rehearsal-apply-rollback-v0111-2026-11-16.json` and `ledger-roles-events-apply-rollback-2026-11-16.json` recorded trigger immutability and full rollback.
- No new shared-database rehearsal was run at this checkpoint.

## T020 — Grants and governance-event candidates

- V0112 asserts DBA-provisioned NOLOGIN NOINHERIT roles and grants writer INSERT-only, reader/auditor SELECT-only.
- V0113 appends governance events with approver separation, dual control, export-before-purge, and append-only protection.
- Both remain speculative candidates outside `sql/migrations/`; behavior evidence is in `ledger-governance-events-behavior-2026-11-16.json`.

## T021 — Retention and incident-response decisions

See `manifest-ledger-governance-policy-draft.md` section “Recorded M1 decisions”. Retention period is still pending legal/owner evidence; interim controls are recorded without claiming implementation.

## T022 — Ledger evidence archive

Existing read/integrity evidence under `sql-candidates/backfill/` is unchanged and remains hash-covered by `evidence-closeout-index.json`: `run-ledger-read-2026-11-16.json`, `run-ledger-integrity-2026-11-16.json`, and `run-ledger-integrity-detects-bad-2026-11-16.json`.

## US2 checkpoint

Manifest/output immutability scaffolding, ledger candidates, retention/incident policy, and retrieval evidence are reviewable. No production persistence, role enforcement, retention job, or promotion claim is authorized.
