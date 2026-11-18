# Implementation Plan (P0, RM-01..07)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | `RM-01..07`, `P0-TSK-001..010`, `AC-P0-01..11` |
| Rule | Implement in dependency order; each work package requires code/schema + tests + manifest/RTM evidence before status changes |

## Work package order

| WP | RM/Tasks | Objective | Key targets (expected) | Depends on | Deliverables |
|---|---|---|---|---|---|
| WP0 | TSK-001, DEC-002/003/004/005/008 | Governance/policy inputs locked for implementation | `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md`, decision tracker, config/policy files | approvals | Recorded decisions, policy versions, holdout spec ref, lock strategy |
| WP1 | RM-01, TSK-016/017 (`P0-TSK-008`) | PIT universe/membership | `sql/migrations/*`, `sql/schema.sql` (canonical as decided), `src/**/universe*`, loaders/scoring/feature/backtest entry points, `reference.securities` handling | WP0 | PIT membership source/history, `eligible_as_of`/as-of filters, `delisted_date`/status history strategy, manifest fields |
| WP2 | RM-02, TSK-014 (`P0-TSK-003`) | PIT timing for fundamentals/features/dividends | feature builders (`src/**/features*`), dividend/fundamental loaders, SQL/views, manifests | WP1 design inputs | `available_at/known_as_of` semantics, filed/accepted persistence where available, removal/guarding of leakage-prone timing |
| WP3 | RM-03, TSK-018/019/020/021 (`P0-TSK-005/006`) | Adjustment/dividend/date/basis integrity | `scripts/populate_dividend_data.py`, `sql/migrations/*`, `raw.dividend_data` model/evidence tables, `src/**/adjust*`, market/dividend consumers | WP1/WP2 interfaces | Feed-evidence retention, deterministic batch pre-dedupe, `COALESCE`/correction policy for non-NULL dates, canonical price/dividend basis & adjustment policy, quarantine/audit hooks |
| WP4 | RM-04, TSK-008/009/010 (`P0-TSK-001/002`) | Immutable manifests and provenance | `src/**/manifest*|run*|artifacts*`, ingest/score/backtest/report pipelines, storage schema/tables | WP0 decisions, WP1-3 contracts | Immutable `run_id` manifests, input/config/policy/code hashes, output refs, append-only provenance |
| WP5 | RM-05, TSK-011/022/023 (`P0-TSK-009`) | Mutable output control & Reports Center provenance/as-of | `app/views/dashboard.py`, report storage/retrieval, scores/AI persistence paths, API/app loaders | WP4 | Run-keyed/versioned outputs, explicit `report_as_of`/`resolved_as_of`/`generated_at`, parameterized loaders, UI labels/metadata |
| WP6 | RM-06, TSK-026 (`P0-TSK-004`) | Reproducible runtime/locks | `requirements*`/lock files, `Dockerfile`, `docker-compose.yml`, CI workflows (if in scope) | WP0 `DEC-008` | Locked/hash-pinned installs enforced in local/CI/Docker, env/lock captured in manifests |
| WP7 | RM-07, TSK-002/003 (`P0-TSK-007/010`) | Verification baseline, evaluation/promotion gates | `tests/**`, eval/benchmark scripts, acceptance-policy config/versioning, CI config | WP1-6 | Leak/adjustment/batch/manifest/report tests, frozen holdout & cost/exposure-matched benchmark wiring, promotion gate checks |

## Concrete implementation contracts

### WP1 — PIT universe (`RM-01`)
- Add PIT membership history (append-only) or equivalent dated eligibility source; do not rely solely on current `reference.securities` status for historical runs.
- Populate/derive `delisted_date` and preserve status change provenance.
- Implement `eligible_as_of(as_of, ...)` and route scoring/features/ranking/backtests through it.
- Record `universe_as_of`, source/version/hash, counts, exclusion reasons in manifests.

### WP2 — PIT timing (`RM-02`)
- Persist and use filing/acceptance/availability timestamps for fundamentals; define `available_at/known_as_of`.
- Audit and replace/guard `GREATEST(filed, period_end)` and any effective-date leakage paths.
- Make dividend “known” semantics explicit (declaration/filed availability vs ex/record/payment).

### WP3 — Adjustments/dividends (`RM-03`)
- **Prices:** define canonical raw/adjusted series and metadata; populate `adjusted_close` (or equivalent) deterministically; align consumers.
- **Dividends loader (`scripts/populate_dividend_data.py`):**
  - pre-dedupe batch rows by conflict key before execute (deterministic precedence: audited correction > completeness > feed/provider priority > latest `retrieved_at` > stable tie-break);
  - change upsert to preserve existing non-NULL date/fields when incoming NULL (`COALESCE(existing, EXCLUDED...)`) unless explicit audited correction path;
  - retain feed/provider/source evidence (append-only evidence table or key redesign as approved);
  - emit dedupe/quarantine/correction audit records.
- **Migration:** introduce evidence/curated structures and backfill/reconcile without destructive loss.

### WP4/WP5 — Manifests and mutable outputs (`RM-04/05`)
- Create immutable run manifest model/API; require manifest for ingest/score/backtest/report material runs.
- Make scores/reports/AI outputs run-keyed and non-overwriting in audit contexts; store `resolved_as_of`, `generated_at`, `code_sha`, input refs, policy/config hashes.
- Reports Center: accept/resolve explicit `report_as_of`, parameterize context loaders, render metadata/provenance, persist or explicitly label transient outputs (per `../06-execution-prep/reports-center-asof-contract-draft.md`).

### WP6 — Reproducibility (`RM-06`)
- Implement chosen lock/hash workflow (`DEC-008`) and enforce in CI/Docker/local install path.
- Capture environment/lock identifiers in manifests.

### WP7 — Evaluation/verification (`RM-07`)
- Implement frozen holdout handling, versioned acceptance policy, cost model and exposure-matched benchmark (`DEC-002/003/004`).
- Keep rule score as production default unless promotion gate passes (`DEC-005`).
- Add/expand automated tests per `validation-plan.md`.

## PR slicing (suggested)
1. Governance/config + lock scaffolding (WP0/WP6 prep, no behavior claim)
2. PIT universe schema + eligibility plumbing (WP1)
3. PIT timing & leakage guards (WP2)
4. Dividend evidence/batch/upsert + migrations (WP3a)
5. Price/dividend adjustment basis & consumers (WP3b)
6. Manifest/provenance framework + pipeline integration (WP4)
7. Reports/scores mutability controls + UI metadata (WP5)
8. Evaluation/benchmark/holdout gates + full test suite (WP7)

Each PR must include tests, migration notes (if any), and RTM/evidence updates.
