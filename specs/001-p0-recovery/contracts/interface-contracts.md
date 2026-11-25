# Interface Contracts: P0 Recovery Foundations

## Scope

P0 exposes validation and evidence interfaces as CLI checkers, read-only database helpers, file artifacts, and UI provenance labels. These contracts describe observable behavior, not implementation details.

## Covered replay path mapping

| Spec path | Repository entry points | Proxy gate |
|---|---|---|
| Universe construction | `scripts/build_historical_universe.py`, `src/crispdm/dividend_universe.py` | Availability basis and decision reference must be recorded. |
| Feature building | `scripts/build_features.py`, `src/crispdm/features.py`, `src/crispdm/feature_window.py` | Availability basis and decision reference must be recorded. |
| Forward-return labeling | `scripts/build_forward_returns.py`, `scripts/label_targets.py`, `src/crispdm/returns.py` | Availability basis and decision reference must be recorded. |
| Score/rank generation | `scripts/score_rank.py`, `src/crispdm/model.py` | Manifest must record the accepted as-of and proxy decision. |
| Backtesting | `scripts/backtest.py`, `src/crispdm/backtest.py` | Evaluation evidence must record the approved basis. |
| Walk-forward evaluation | `scripts/evaluate_walk_forward.py` | Evaluation evidence must record the approved basis. |
| Report rendering | `app/views/dashboard.py` | As-of/provenance display only; no new proxy data use. |

## CLI checker contract

Common exit codes for checker commands:

| Code | Meaning |
|---:|---|
| 0 | Requested static/read-only checks passed; not a promotion claim. |
| 1 | Validation/conflict/incomplete evidence found. |
| 2 | Usage, safety refusal, unreadable input, or database error. |

All database-aware checkers must:

- Refuse non-local/shared-like targets unless explicitly allowed.
- Open a read-only transaction.
- Emit sanitized target metadata without credentials.
- Never create, update, or delete rows.

### Commands

| Command | Input | Success condition | Non-success condition |
|---|---|---|---|
| `check_migration_candidates.py` | Candidate directory and migration directory | Candidate names/hashes/dependencies/rollbacks are consistent | Missing hash, collision, destructive forward SQL, or rollback issue |
| `check_candidate_backfill_readiness.py` | Static by default; optional explicit DSN | Static checks pass or read-only data checks all pass | Missing schema, incomplete backfill, anomaly, or safety refusal |
| `check_manifest_ledger_policy.py` | Governance policy JSON | Draft structure and safety invariants pass | Unsafe privileges, missing approval fields, or unmet `--require-approved` |
| `check_manifest_ledger_integrity.py` | Explicit DSN | Manifest hash/columns/keys and output linkage are consistent | Hash mismatch, drift, orphan, missing ledger, or safety refusal |
| `check_promotion_evidence.py` | Checkpoint/backtest/manifest/policy paths | Draft structure checks pass | Missing fields or unmet `--require-promotion-grade` |
| `check_reproducibility_locks.py` | Lock file paths | Lock files exist and parse as pinned entries | Missing/empty/invalid lock file |
| `check_reproducibility_enforcement.py` | Repository root | Draft gap report produced | Missing artifact or unmet `--require-enforced` |
| `check_evidence_closeout.py` | Evidence index and root | Hash-verified evidence bundle remains non-promotion | Missing artifact, hash mismatch, or promotion claim |
| `show_run_ledger.py` | Run ID and explicit DSN | Manifest/output bundle found | Not found, missing ledger, or safety refusal |

## Write-path contracts

### Manifest persistence

Command: `persist_run_manifest.py`

- Default is dry-run; no database access.
- Writing requires `--persist --i-understand-ledger-write` and an explicit DSN.
- Existing `run_id` with identical hash is a no-op.
- Existing `run_id` with different hash is a conflict and must fail.
- No table creation, update, or delete is permitted.

### Run output persistence

Command: `persist_run_output.py`

- Default is dry-run; no file write.
- Writing requires `--write --i-understand-run-output-write`.
- Storage is `<root>/<run_id>/<output_kind>.json`.
- Identical payload reruns are idempotent.
- Differing payloads under the same run/output pair must fail.
- Run and output-kind values must be safe path components.

### Governance event records

Candidate table: `audit.ledger_governance_events`

- Event types are limited to incident, hold, export, purge, and break-glass events.
- Approver must differ from actor.
- Legal holds, purges, and break-glass events require dual control.
- Purge completion requires an export reference.
- Records are append-only in the candidate design.

## Artifact contracts

### Run manifest

Required fields: `run_id`, `run_type`, `created_at_utc`, `code`, `parameters`, `inputs`, `outputs`, `environment`, `hashes`.

Validation:

- Hash must match canonical JSON.
- Run ID must match ledger row key when persisted.
- Dependency lock hashes must be present when available.

### Candidate evidence bundle

Required properties:

- Hash-locked evidence index.
- Explicit `promotion_claim=false`.
- Candidate/promotion/reproducibility policies remain draft or unapproved.
- Checker validation passes without modifying artifacts.

### Reports Center provenance

Each report must display:

- Resolved as-of date.
- Generated time.
- Run reference.
- Storage mode.
- Historical-selection limitation when unavailable.

## Safety contract

- No command may silently switch context from dry-run to write.
- No command may write to shared/production targets without explicit override.
- No command may imply approval, promotion, or AC verification by exit code alone.
- Candidate schemas must remain outside `sql/migrations/` until approval.
