# Executive Summary — Existing Trading Platform Modernization

| Field | Value |
|---|---|
| Stage | 5 — Spec Kit artifacts (one-page max) |
| Date | 2026-11-15 (snapshot `d748cea`) |
| Baseline | 84 recovered requirements: 18 Implemented, 53 Partial, 12 Missing, 1 Unknown; 30 principle evidence rows (3 Practised/11 Partial); 95 constitution rules (30 Descriptive/65 Aspirational) |

## Top findings
- **PIT integrity is the dominant gap:** survivorship/current-state universe and filing/timing defaults leak future/current information (`FR-UNI-01`, `FR-DIV-03/07`, `NFR-PIT-01..05`, `RK-01/02/09`).
- **Decision evidence is not reproducible:** scores/labels/checkpoints/artifacts are mutable or lack manifests/run identity and complete lineage (`FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`, `NFR-AUD/REPRO`, `RK-03/04/07`).
- **Evaluation is not decision-grade:** no costs, unmatched benchmark, reused/changed policy context, stale artifacts (`FR-EVAL-03`, `FR-BT-03/04`, `RK-04`).
- **Runtime and verification are weak:** unpinned/no-lock environment, installed drift, broken dry-run, no coverage/PIT-determinism/CLI gates (`NFR-REPRO-01/02`, `NFR-TEST-01..04`, `RK-06/08`).
- **Strengths to preserve:** API auth/rate limiting, ops allowlist, read-only explorer, non-root containers, audit/quarantine/freshness controls, modular layering, rule-based production scoring (`NFR-SEC-01..03`, `NFR-GOV-02`, `PE-26/27/29`, `FR-SIG-01`).

## Scorecard
| Domain | Score | Key condition to improve |
|---|---:|---|
| CRISP-DM compliance | 2.8 / 5 | Evaluation/PIT controls verified with manifests and matched benchmarks |
| Research governance | 2.0 / 5 | Policy/holdout/run lineage enforced; provider terms resolved |
| Reproducibility | 1.5 / 5 | Hashed lock, manifests, immutable artifacts, clean replay passes |
| Production readiness | 2.5 / 5 | PIT/correctness fixes, reliability hardening, blocking gates |

## Top 5 risks
| Rank | ID | Severity | Risk |
|---|---|---|---|
| 1 | RK-01 | Critical | Survivorship-biased universe / no PIT membership (`FR-UNI-01`, `NFR-PIT-02`) |
| 2 | RK-02 | Critical | Future/current leakage in dividends, eligibility and timing defaults (`FR-DIV-03/07`, `NFR-PIT-01/03/04`) |
| 3 | RK-03 | Critical | Mutable/overwritten decision evidence and missing run manifests (`FR-SIG-03`, `FR-LABEL-03`, `FR-EVAL-04`, `FR-BT-05`) |
| 4 | RK-04 | Critical | Non-decision-grade backtest/evaluation evidence (no costs, unmatched benchmark, reused holdout) (`FR-EVAL-03`, `FR-BT-03/04`) |
| 5 | RK-06 | High | Runtime not reproducible (unpinned deps, no lock, drift) (`NFR-REPRO-01/02`) |

## Recommended first 30 days
| Day range | Actions | Traceability |
|---|---|---|
| Days 1–10 | Approve constitution + Critical exception log; decide holdout/policy/cost/benchmark/terms owners; define manifest/artifact contract and RTM/change-trace workflow. | `TSK-001..004,008,014,015`, `RK-01..04/13`, `RM-04/12` |
| Days 11–20 | Restore reproducible runtime baseline (pins/hashed lock, CI/Docker/local alignment); fix/contain broken dry-run; add CI coverage tooling/threshold and CLI smoke-test skeleton. | `TSK-009,010,026`, `NFR-REPRO-01/02`, `NFR-TEST-01/04`, `RK-06/08`, `RM-06/07` |
| Days 21–30 | Specify and prototype PIT + evidence foundations: PIT membership/filed-as_of design, run-keyed manifest/store schema, initial PIT/determinism regression tests, and readiness gate criteria for M2/M3. | `TSK-011,016,017,020,022,023,028`, `RK-01/02/03/07`, `RM-01/02/04/05/07` |
