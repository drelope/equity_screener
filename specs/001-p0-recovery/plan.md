# Implementation Plan: P0 Recovery Foundations

**Branch**: `feature/speckit-recovery` | **Date**: 2026-11-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-p0-recovery/spec.md`

**Status**: Approved at review-plan gate (2026-11-18) — local implementation validation complete except approval-gated tasks; M1/CI evidence pending; merge and release blocked

## Summary

P0 Recovery Foundations hardens the existing equity/dividend platform rather than replacing it. The work is organized around five linked capabilities:

1. Point-in-time correct universes, timing, and dividend inputs.
2. Immutable, run-addressable evidence with manifests and output references.
3. Evaluation bundles with formation rules, cost assumptions, and exposure-matched comparisons.
4. Reproducible dependency identity and blocking verification gates.
5. Explicit governance of approvals, exceptions, and unresolved external evidence.

The committed P0 work on `feature/speckit-recovery` provides scaffolding and evidence for these capabilities. This plan traces that work to the approved spec and identifies the remaining verification and cutover gates. It does not authorize promotion, production cutover, or new AI-IOS platform capabilities.

## Technical Context

**Language/Version**: Python 3.11 locally; Python 3.12 in CI and Docker. DEC-008 must ratify the canonical target before enforced lock parity.

**Primary Dependencies**: SQLAlchemy/psycopg for database access; pandas/numpy/scikit-learn for research computation; Streamlit and FastAPI for UI/API; OpenBB provider integrations. Existing lock drafts are `requirements.lock.txt` and `requirements-dev.lock.txt`.

**Storage**: PostgreSQL 17.11 with `raw`, `reference`, `clean`, `model`, `audit`, and `analysis` schemas. File artifacts live under gitignored `artifacts/`. Candidate ledger tables are defined in `docs/speckit-recovery/08-implementation-validation/sql-candidates/V0110..V0113` and are not applied.

**Testing**: `pytest`; `ruff check .`; `ruff format --check .`; candidate/evidence checker scripts. The last full local suite was 2,060 passed, 0 failed. CI has not been run externally.

**Target Platform**: Local Linux/WSL development, disposable Docker Postgres rehearsals, Ubuntu CI, and existing Docker Compose deployment.

**Project Type**: Existing multi-entry-point data/research platform: Python library modules, CLI scripts, Streamlit UI, FastAPI API, SQL schema/migrations, and ops worker.

**Performance Goals**: No new P0 latency or throughput SLA. Preserve current operational behavior; measure candidate queries and dual-read paths before any cutover.

**Constraints**:

- No shared/production database writes during candidate validation.
- Candidate SQL remains outside `sql/migrations/` until approval gates close.
- No requirement, holdout, cost-model, benchmark, or promotion claim may be accepted without recorded evidence.
- Existing security, least-privilege, audit, and quarantine controls must be preserved.
- AI-IOS is a non-normative future-vision reference only.

**Scale/Scope**: 84 recovered requirements, P0 work packages RM-01..RM-07, 7 numbered migration candidates, 37-artifact evidence closeout bundle, and a full local regression suite of 2,060 tests.

## Constitution Check

**Gate status: PENDING EXTERNAL M1 APPROVAL; LOCAL IMPLEMENTATION VALIDATION ONLY.**

`.specify/memory/constitution.md` contains the prepared project constitution draft. M1 approval has been requested but not supplied; no external approval or CI status is recorded. Aspirational rules remain targets until verification evidence exists.

| Principle area | Plan treatment | Evidence / residual gate |
|---|---|---|
| Shared truth | PIT metadata and manifest lineage are traceable to run context. | Consumer cutover and survivor-vs-PIT comparison remain approval-gated. |
| Governance first | Promotion and migration candidates are explicit non-applied artifacts. | M1/EX/DEC/UNK approvals pending. |
| Forecast accountability | Evaluation evidence requires policy, costs, net results, and matched comparison. | Holdout freeze, economics, and statistical validity are external evidence. |
| Reproducibility | Lock drafts, manifest lock hashes, and CI gap reporter exist. | DEC-008 lock strategy and CI/Docker enforcement pending. |
| No destructive evidence loss | Append-only stores, conflict refusal, and rollback rehearsals are used. | Retention/incident model pending; candidate promotion not approved. |

No constitution violation is claimed. M1 disposition and EX/DEC/UNK recommendations are prepared in `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md`, and the draft constitution is in `.specify/memory/constitution.md`. Local implementation validation is complete; merge, release, promotion, and cutover remain blocked until external approval evidence is supplied.

## Project Structure

### Documentation (this feature)

```text
specs/001-p0-recovery/
├── spec.md                  # Approved user-facing specification
├── plan.md                  # This file (/speckit.plan output)
├── research.md              # Phase 0 output (/speckit.plan output)
├── data-model.md            # Phase 1 output (/speckit.plan output)
├── quickstart.md            # Phase 1 output (/speckit.plan output)
├── contracts/               # Phase 1 output (/speckit.plan output)
├── checklists/
│   └── requirements.md      # Spec quality checklist
└── tasks.md                 # Phase 2 output (/speckit.tasks; not created here)
```

### Source Code (repository root)

```text
src/crispdm/
├── pit.py                   # PIT context/metadata helpers
├── feature_window.py        # Feature window and embargo metadata
├── features.py              # Feature builder integration
├── returns.py               # Forward-return timing metadata
├── model.py                 # Scoring model PIT context
├── run_manifest.py          # File manifests, hashes, lock hashes
├── manifest_store.py        # Candidate ledger manifest/output persistence
├── output_store.py          # Run-keyed output artifacts
└── analysis/                # Worksheet/report store support

scripts/
├── build_features.py, build_forward_returns.py, label_targets.py,
│   score_rank.py, backtest.py, evaluate_walk_forward.py              # Manifest/PIT integration
├── populate_dividend_data.py, populate_audit.py, populate_market_data.py
├── check_migration_candidates.py, check_candidate_backfill_readiness.py,
│   check_manifest_ledger_policy.py, check_manifest_ledger_integrity.py,
│   check_promotion_evidence.py, check_reproducibility_locks.py,
│   check_reproducibility_enforcement.py, check_evidence_closeout.py
├── persist_run_manifest.py, persist_run_output.py, show_run_ledger.py
└── rehearse_p0_drafts.py, rehearse_p0_full.py, rehearse_backfill_synthetic.py

app/
├── views/dashboard.py       # Reports Center provenance labels
└── nav.py                   # Cross-page flow/navigation

tests/                       # Unit, integration, and checker tests

docs/speckit-recovery/08-implementation-validation/
├── sql-drafts/              # Initial additive DDL drafts
├── sql-candidates/          # Numbered V0107..V0113 candidates and evidence
└── *.md / *.json            # Status, RTM, policy, closeout artifacts

docs/speckit-recovery/09-future-vision/
├── AI-IOS-source.md         # Non-normative external source
└── AI-IOS-traceability.md   # Scope classification

.github/workflows/ci.yml      # Lint, test, security, reproducibility, closeout jobs
```

**Structure Decision**: Extend the existing modular platform; do not introduce a new application, agent framework, Macro State Engine, TradingView integration, Redis service, DuckDB store, or Kubernetes topology for P0. New design artifacts live only under `specs/001-p0-recovery/`; implementation evidence remains under `docs/speckit-recovery/08-implementation-validation/`.

## Complexity Tracking

No new structural complexity is introduced by this plan. The pending M1 ratification is recorded above as a governance gate, not as a design violation requiring a complexity exception.
