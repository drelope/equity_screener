# Stage 4 Summary — Synthesis and Migration Planning

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Status | Complete |
| Snapshot | `d748cea` at `2026-11-15` |
| Inputs | `docs/speckit-recovery/00-discovery/`, `01-audits/`, `02-requirements/`, `03-constitution/` |
| Outputs | `risk-register.md`, `remediation-plan.md`, `migration-roadmap.md`, `compliance-scorecard.md`, `migration-readiness.md`, `STAGE_SUMMARY.md` |
| Source edits | None |

## 1. What Was Done
- Read Stage 0–3 summaries/registers and synthesized cross-stage findings (`PA/BI/TG/DA`, `FR/NFR`, `PE`, constitution rules) into migration-focused artifacts.
- Merged and de-duplicated prior findings into 15 consolidated risks with likelihood/impact/severity, ownership and mitigations.
- Produced a prioritized remediation plan (P0–P2, 13 actions) grouped by bias/PIT, determinism, tests, auditability/lineage, reproducibility, reliability, documentation and technical debt with effort, dependencies and verification.
- Defined a 6-phase migration roadmap (Phases 0–5) with goals, deliverables, exit/success criteria, risks, dependencies and milestones.
- Scored CRISP-DM compliance, research governance, reproducibility and production readiness with evidence-based justification and post-remediation targets.
- Assessed migration readiness across architecture, dependencies, technical debt, portability, schema evolution and deployment automation.

## 2. Files Produced
| File | Contents |
|---|---|
| `docs/speckit-recovery/04-migration/risk-register.md` | 15 de-duplicated risks (`RK-01..RK-15`), severity/ownership/mitigation, evidence refs, critical path. |
| `docs/speckit-recovery/04-migration/remediation-plan.md` | 13 prioritized actions (`RM-01..RM-13`, P0–P2) with grouping, effort, dependencies and verification. |
| `docs/speckit-recovery/04-migration/migration-roadmap.md` | Phases 0–5 plan with deliverables, exit/success criteria, risks, dependencies, milestones M1–M5. |
| `docs/speckit-recovery/04-migration/compliance-scorecard.md` | Scores: CRISP-DM 2.8/5, research governance 2.0/5, reproducibility 1.5/5, production readiness 2.5/5 with targets. |
| `docs/speckit-recovery/04-migration/migration-readiness.md` | Conditional/partial readiness assessment by dimension, strengths to preserve, blocking conditions and gate. |
| `docs/speckit-recovery/04-migration/STAGE_SUMMARY.md` | This summary and Stage 5 handoff. |

## 3. Key Synthesis
- **Critical path:** PIT integrity (RK-01/02/09/10) -> append-only decision evidence/manifests (RK-03/04/07) -> reproducibility and blocking test gates (RK-05/06/08).
- **Highest-severity themes:** survivorship/PIT leakage, mutable decision evidence, non-decision-grade backtests, adjustment uncertainty, unpinned/unreproducible runtime, weak lineage/manifests, and insufficient regression gates.
- **Strengths to preserve:** security/least-privilege controls, audit/governance primitives (quality/quarantine/freshness/migrations where present), modular layering and recovered traceability artifacts.
- **Overall posture:** conditional/partial readiness; not yet suitable for trustworthy promotion claims or unmanaged modernization.

## 4. Open Questions (carry-forward)
- `NFR-GOV-03`/`RK-13`: provider licensing/terms for internal use, caching, redistribution and derived data (yfinance, FMP, SEC, others).
- Ownership/storage of frozen holdout and acceptance-policy versions (`FR-EVAL-03`, RM-04).
- Cost model and exposure-matched benchmark definition for decision-grade backtests (`FR-BT-03/04`, RM-03).
- Raw close and dividend/split basis confirmation (`FA-U01`, `FA-U03`, RM-10).
- Authoritative migration state given 104 files vs applied ledger 106 (`PE-23`, RM-12).
- Streamlit direct warehouse-read boundary and `sql/silver_schema.sql` disposition (`PE-21/25`, RM-13).
- Unverified external scheduler/object-store/backup state and unresolved BI-01 magnitude, BI-37, DA-21.

## 5. Handoff Notes for Stage 5
- Use `risk-register.md` and `remediation-plan.md` as the source for Spec Kit problem/risk/requirement prioritization; do not draft specs that assume PIT, immutable evidence, manifests, costs/benchmark or reproducible runtime already exist.
- Preserve descriptive-vs-aspirational separation from Stage 3 and trace Stage 5 artifacts to `FR/NFR/PE/RK/RM` IDs.
- Treat RK-01..RK-08 / RM-01..RM-07 as P0 foundations; require explicit exceptions for Critical requirements `FR-UNI-01, FR-DIV-07, NFR-PIT-01, NFR-PIT-02`.
- Update RTM/constitution references if Stage 5 drafting reveals conflicts; do not silently reconcile.
