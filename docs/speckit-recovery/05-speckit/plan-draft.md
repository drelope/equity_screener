# Existing Trading Platform Modernization — Plan Draft

| Field | Value |
|---|---|
| Stage | 5 — Spec Kit artifacts |
| Date | 2026-11-15 |
| Inputs | Stage 0–4 recovery artifacts (`docs/speckit-recovery/00-discovery..04-migration/`) |
| Traceability | `CMP/SVC/EP/DF/CAP`, `FR/NFR`, `PE`, `RK-01..15`, `RM-01..13` |

## Architecture Summary
- **Current shape (recovered):** modular Python/Postgres platform with domain logic in `src/crispdm`, API in `api/`, Streamlit UI in `app/`, ops in `ops/`, SQL/schema/migrations in `sql/`, and scripts/CLIs for ETL, scoring, evaluation and backtest (`PE-20/24`, `CMP-01..20`).
- **Data/control flow:** external providers/SEC/market inputs -> ingestion/loaders -> warehouse (`raw/reference/clean/model/audit/analysis` schemas) -> features/scoring/portfolio/backtest/analytics -> API/UI/reports; ops catalog/worker orchestrates allowlisted tasks (`DF-*`, `SVC-*`, `EP-*`).
- **Production decision path:** rule-based scoring is the production ranker; ML is a gated research path (`FR-SIG-01`, `FR-EVAL-02`, `GP-02`, `DC-01`).
- **Target modernization posture:** preserve modular/security strengths while adding PIT-correct inputs, append-only run-keyed evidence, manifests/lineage, reproducible runtime, and blocking verification gates (`RM-01..07`, constitution aspirational rules).

## Component/Service/Data Pipeline Inventory
| Layer | Inventory (IDs) | Notes |
|---|---|---|
| Components | `CMP-01..CMP-20` | Config/DB, SEC & market clients, loaders, schema/migrations, ETL orchestrator, dividend/fundamentals, features, scoring, portfolio/backtest/analytics, API, Streamlit UI, worksheet, ops, agent framework, explorer, audit/verification, macro, API client, LLM draft client |
| Services | `SVC-01..SVC-11` | Warehouse/runtime services and operational pathways per Stage 0 service inventory (UI, API, ETL/nightly, ops worker, audit/verification, etc.) |
| Entry points / workflows | `EP-01..EP-24` | UI pages/workflows, API endpoints, CLIs, jobs/schedulers (56 root scripts with `__main__`; ops-cataloged tasks) |
| Data flows | `DF-01..DF-20` | Provider ingestion, corporate actions/splits, dividend reconciliation, feature/score/forward-return builds, backtest/reporting, audit lineage/quality/freshness |
| Capabilities | `CAP-01..CAP-25` | Present/Partial/Absent capability baseline; watchlist/alerts and AI summarization absent, ML research-gated |

## Datastores
| Store/schema area | Role | Evidence highlights | Readiness concerns |
|---|---|---|---|
| `raw.*` (market_data, dividend_data, corporate_actions, macro, SEC payloads/calendars) | Source-of-record ingested data | 9.8M prices (`adjusted_close` 100% NULL), 323k dividends, 105k macro vintages, 2,121 calendar events | PIT/lineage gaps, latest-only payloads, dividend key/NULL-overwrite/quarantine issues (`RK-02/05/07/10`) |
| `reference.*` | Security/identifier/reference metadata | `securities`, `security_identifiers` (0 closed ticker intervals noted) | No PIT membership/identity validity as required (`FR-UNI-01`, `FR-ID-01`, `RK-01`) |
| `clean.*` / fundamentals-related tables | Normalized inputs | Used by features/analytics pipelines | Adjustment/basis consistency and availability semantics need hardening (`FR-ADJ/TR/FEAT`) |
| `model.*` (features, scores, rankings, predictions, forward_returns) | Research/model outputs | 9.76M features (`features_v5` hash), 464k scores, 467k predictions, 216 run ids, 8.28M forward returns | Scores/labels mutable or not run-addressable; features lack rebuild/input snapshot identity (`RK-03/07`) |
| `audit.*` | Quality, quarantine, freshness, lineage, runs | 343k data_quality, 2,698 quarantined, 72 freshness, 26k lineage, 53 nightly, 18 model runs | Lineage narrow/destructive; run rows lack code/env/input identity (`RK-07/11`) |
| `analysis.*` | Investment worksheet persistence/revisions | 18-section worksheet workflow | Reports/worksheets need resolved as-of stamping and bounded AI behavior (`RK-09`) |
| Artifacts/files | Backtest metrics/periods, checkpoints | 7 backtest metric files; canonical checkpoint overwritten; no manifests | Not decision-grade/replayable (`RK-03/04`) |

## Technology Stack
| Category | Current | Evidence | Plan implication |
|---|---|---|---|
| Language/runtime | Python (3.12 in Docker/CI) | `Dockerfile`, `.github/workflows/ci.yml` | Pin runtime and lock deps consistently (`RM-06`) |
| Database | PostgreSQL 17.11, SQL migrations | `docker-compose.yml`, `sql/schema.sql`, 104 migration files / ledger max 106 | Reconcile ledger; plan append-only/PIT migrations carefully (`RM-04/05/12`) |
| API/UI | FastAPI, Streamlit | `api/main.py`, `app/streamlit_app.py` | Preserve auth/boundaries; add as-of stamping and boundary decisions (`RM-09/12/13`) |
| Data/ML libs | pandas/numpy/scikit-learn/SQLAlchemy/psycopg etc. | `requirements*`, `src/crispdm/*` | Hashed lock and env manifests required (`NFR-REPRO-01..02`) |
| Testing/quality | pytest, ruff, pip-audit, gitleaks | 1,929 collected tests, CI lint/test/security jobs | Add coverage/PIT/determinism/CLI gates (`RM-07`) |
| Ops/deploy | Docker Compose, ops catalog/worker, advisory lock | `CMP-14`, `run_full_etl.py`, `ops/*` | Harden reliability, checkpoints/resume, diagnostics (`RM-11`) |

## Technical Assumptions
- **TA-01 (Assumption, flagged):** incremental schema evolution can introduce run-keyed/append-only structures and PIT intervals without unacceptable downtime if backfills/recomputes are planned (depends on RM-04/05/01 design).
- **TA-02 (Assumption, flagged):** a single dependency/lock strategy can be adopted across local/CI/Docker (RM-06 decision pending).
- **TA-03 (Assumption, flagged):** representative performance budgets can be defined from current volumes (9.8M prices, 9.76M features) without full production telemetry (`NFR-SCALE-02`, `RK-14`).
- **TA-04 (Unknown carried):** external orchestration, object-store, backup/restore and provider audit-log capabilities are outside inspected scope (`RK-13`).
- **TA-05 (Unknown carried):** canonical adjustment basis and provider amount/split semantics require validation before final correction (`FA-U01/U03`, `RK-05`).

## Workstreams
| Workstream | Objectives | Primary actions | Key traceability |
|---|---|---|---|
| Governance | Approve constitution, exceptions, policies, inventories, doc alignment | Exception log for Critical reqs; provider terms/secret rotation; RTM/constitution/doc reconciliation; migration ledger reconciliation | `RM-12`, `NFR-GOV-*`, `NFR-SEC-03`, `CM-*`, `RK-12/13/15` |
| Data | PIT correctness, dividend/identity/adjustment integrity, lineage | PIT membership/identity intervals, filed/as-of enforcement, dividend key/COALESCE/quarantine, adjustment chain validation, append-only payloads/lineage | `RM-01/02/05/08/09/10`, `FR-UNI/ID/DIV/ADJ/CA/TR/FEAT/LABEL/MACRO`, `NFR-PIT/AUD`, `RK-01/02/05/07/09/10` |
| Analytics | Decision-grade evaluation/backtest and reproducible outputs | Run-keyed immutable scores/labels/checkpoints/artifacts, manifests, costs/exposure-matched benchmarks, formation-correct backtests, as-of reports/worksheets | `RM-03/04/09`, `FR-SIG/EVAL/BT/PORT/REP/AI`, `NFR-REPRO/AUD`, `RK-03/04/09` |
| Testing | Prevent regression and prove controls | Hashed lock-aligned CI, coverage threshold, CLI smoke, PIT/frozen-clock/determinism, SQL-contract/artifact-compatibility, perf budgets | `RM-06/07/10/11`, `NFR-TEST/DET/SCALE`, `RK-06/08/14` |
| Auditability | End-to-end traceable runs and provenance | Manifest schema/completeness checks, env/code/input/policy identity, lineage expansion, append-only history, compatibility checks | `RM-04/05/11`, `NFR-AUD/REPRO`, `PE-03/04/07/08/11/12` |
| Migration | Phased delivery and controlled adoption | Execute roadmap Phases 0–5 with milestones M1–M5, backfill/recompute planning, controlled cutover/readiness gates | `RM-01..13`, `RK-01..15`, Stage 4 roadmap/readiness |

## Success Metrics
| Metric | Baseline (2026-11-15) | Target | Traceability |
|---|---|---|---|
| Requirements status | 18 Implemented / 53 Partial / 12 Missing / 1 Unknown | P0 Critical/High gaps closed or formally excepted; Missing reduced for PIT/evidence/repro/test scope | Stage 2 register, `RM-01..07` |
| PIT verification | All `NFR-PIT-01..05` Partial; no PIT regression suite | PIT suite passes; no wall-clock/current-state replay defaults; survivor-vs-PIT delta reported | `AC-01`, `RK-01/02/09` |
| Decision evidence | Scores/labels/checkpoints/artifacts mutable or non-manifested | 100% scoped runs/artifacts run-keyed with complete manifests and append-only lineage | `AC-02`, `RK-03/04/07` |
| Evaluation rigor | No costs, unmatched benchmark, reused holdout | Frozen policy + untouched holdout recorded; costs and exposure-matched benchmark present | `AC-03`, `RK-04` |
| Runtime reproducibility | Unpinned worktree, no lock, drift | Hashed lock; identical CI/Docker/local installs; env identity recorded | `AC-04`, `RK-06` |
| Test gates | No coverage gate; CLI/PIT/determinism gaps; dry-run broken | Coverage threshold enforced; CLI smoke + PIT/determinism/SQL-contract/artifact checks blocking | `AC-04`, `RK-08` |
| Operations | 4 recent nightly failures; no resume/root-cause | Diagnosable failures, resume/timeouts/alerts, contention tests passing | `AC-05`, `RK-11` |
| Compliance scorecard | CRISP-DM 2.8, governance 2.0, reproducibility 1.5, production readiness 2.5 | >=3.5 each after Phase 4 conditions met | Stage 4 scorecard |

## Milestones
| Milestone | Phase | Target outcome | Exit signal |
|---|---|---|---|
| M1 | Phase 1 Constitution | Approved constitution, owners, Critical exception log | Rules mapped to verification/enforcement |
| M2 | Phase 2 Specification Recovery | Approved P0/P1 specs with acceptance tests and migration impacts | `RM-01..07` traceable to specs/RTM |
| M3 | Phase 3 Traceability Foundation | Manifest/lock/append-only lineage foundation working in controlled replay | Scoped run reproducible from manifest |
| M4 | Phase 4 Validation & Refactoring | P0 complete, P1 materially complete or controlled; gates green | PIT/evidence/repro/test blocking conditions cleared or excepted |
| M5 | Phase 5 Adoption | Spec-driven workflow sustained across changes | Specs/tests/RTM/docs/manifests updated together |

## Risks
- **Delivery/correctness:** historical recomputes may change results; adjustment basis unknowns (`FA-U01/U03`) can delay `RM-10`.
- **Governance blockers:** provider terms, cost model, benchmark, holdout ownership unresolved (`NFR-GOV-03`, `RK-04/13`).
- **Migration complexity:** append-only/run-keyed schema and PIT interval migrations/backfills (`RM-01/04/05`).
- **Adoption risk:** aspirational constitution rules not enforced; process bypass under pressure (`RK-12`, Phase 5 risks).
- **External dependencies:** scheduler/object-store/backup/provider behavior outside inspected scope (`RK-13`, TA-04).
