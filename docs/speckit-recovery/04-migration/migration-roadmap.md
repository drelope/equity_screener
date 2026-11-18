# Stage 4 Migration Roadmap

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Target | Move from recovered baseline to evidence-backed, spec-driven development without assuming unimplemented controls exist |

## Phase overview

| Phase | Name | Goals | Key deliverables | Exit criteria | Success criteria | Risks | Dependencies |
|---|---|---|---|---|---|---|---|
| 0 | Discovery & Baseline | Freeze recovered understanding and known gaps | Stage 0–4 recovery artifacts accepted; baseline metrics (84 req, 18/53/12/1, 30 PE, 95 rules, 15 risks) | Stakeholders acknowledge baseline, open questions and critical risks | Single source of truth for current state; no undocumented assumptions treated as fact | Baseline disputed or ignored | Access to recovery docs and prior audit evidence |
| 1 | Constitution | Adopt governing rules and decision gates | Approved constitution (descriptive+aspirational labeled), rule owners, exception log for Critical reqs | Constitution approved with MUST/SHOULD verification methods and exception handling for RK-01..04 | All changes evaluated against constitution; Critical exceptions time-bounded | Rules accepted without enforcement | Phase 0; ownership/legal/security input |
| 2 | Specification Recovery | Convert recovered requirements into implementation-grade specs | Prioritized specs for PIT, dividend integrity, manifests/immutability, reproducibility, test gates; RTM updates | Specs accepted for P0/P1 scope with acceptance tests and migration impacts | Every P0/P1 remediation item traceable to spec + requirement + risk + PE | Specs mirror current defects instead of required behavior | Phase 1; decisions on costs/benchmark/holdout/provider terms |
| 3 | Traceability Foundation | Build the evidence substrate before behavior claims | Run manifest schema, append-only stores/lineage plan, hashed lock/CI alignment, artifact contracts, migration ledger reconciliation | Foundation implemented and validated in non-prod/replay context | Runs/artifacts addressable and reproducible; lineage covers model inputs; env pinned | Large schema/data migration complexity | Phases 1–2; RM-04..06 design |
| 4 | Validation & Refactoring | Remediate PIT/bias/correctness and harden tests | PIT membership and filed/as-of enforcement, dividend/price fixes, macro/report as-of, CLI/PIT/determinism/load tests, reliability improvements | P0/P1 acceptance criteria met; blocking CI/release gates pass; survivor-vs-PIT and benchmark/cost evidence published | Material bias/leakage risks reduced; regressions caught by gates; promotion evidence reproducible | Refactor breaks behavior; data backfill/recompute cost | Phase 3; RM-01..03,07..11 |
| 5 | Spec-Driven Development Adoption | Operate new work under spec/test/traceability discipline | Change template/checklists, release gates, maintained RTM/constitution, runbooks, adoption review | Two+ change cycles completed with specs, manifests, tests and docs updated together | No untraced behavior changes; artifacts decision-grade; constitution rules enforced, not aspirational-only | Process bypassed under delivery pressure | Phases 1–4; team training and ownership |

## Phase details

### Phase 0 — Discovery & Baseline
- **Goals:** preserve factual recovery baseline; align on critical risks/open questions.
- **Deliverables:** Stage 0–4 package, risk register acceptance, open-question owners.
- **Exit criteria:** baseline signed off; no P0 work starts on unverified assumptions.
- **Success criteria:** planning and specs cite `FR/NFR/PE/RK` IDs consistently.
- **Risks:** treating Partial/Missing controls as production-ready.
- **Dependencies:** none beyond repository and recovery artifacts.

### Phase 1 — Constitution
- **Goals:** convert evidence into enforceable engineering/governance rules.
- **Deliverables:** approved `constitution-draft` disposition, exception register (esp. `FR-UNI-01, FR-DIV-07, NFR-PIT-01, NFR-PIT-02`), rule verification mapping.
- **Exit criteria:** owners assigned; enforcement mechanism identified per MUST rule.
- **Success criteria:** CI/review gates mapped to constitution rules.
- **Risks:** descriptive controls mistaken for sufficient; aspirational rules left unenforced.
- **Dependencies:** Phase 0.

### Phase 2 — Specification Recovery
- **Goals:** define target behavior and acceptance criteria before remediation coding.
- **Deliverables:** specs for PIT integrity, dividend/adjustment correctness, append-only evidence/manifests, reproducibility, and test/release gates; updated RTM.
- **Exit criteria:** P0 specs approved with acceptance tests and data migration impact.
- **Success criteria:** implementation tasks can be estimated and verified without rediscovering intent.
- **Risks:** scope creep; unresolved policy questions blocking specs.
- **Dependencies:** Phase 1; decisions for RM-03/RM-04/RM-12.

### Phase 3 — Traceability Foundation
- **Goals:** make changes observable and reproducible.
- **Deliverables:** manifest schema, run-keyed storage plan/migrations, lineage expansion, hashed lock + CI/Docker alignment, artifact contract validator, migration ledger reconciliation.
- **Exit criteria:** can reproduce a scoped run end-to-end from manifest in controlled environment.
- **Success criteria:** no critical artifact lacks run/code/env/input identity.
- **Risks:** migration downtime/backfill complexity; compatibility with existing consumers.
- **Dependencies:** Phases 1–2.

### Phase 4 — Validation & Refactoring
- **Goals:** remove highest-severity correctness/bias gaps and institutionalize regression protection.
- **Deliverables:** PIT/delisting fixes, dividend and price-adjustment corrections, as-of macro/reports, reliability improvements, coverage/PIT/determinism/CLI/load tests, refreshed evaluation evidence with costs and matched benchmark.
- **Exit criteria:** P0 complete, P1 materially complete or accepted with controls; release gates green.
- **Success criteria:** Critical/High PIT and evidence risks reduced with measured deltas.
- **Risks:** historical recompute changes results; residual unknowns (FA-U01/U03/provider terms).
- **Dependencies:** Phase 3.

### Phase 5 — Spec-Driven Development Adoption
- **Goals:** prevent regression to undocumented behavior.
- **Deliverables:** enforced change workflow (spec -> tests -> implementation -> RTM/docs/manifest), periodic constitution/RTM review, operational runbooks.
- **Exit criteria:** sustained compliance across multiple changes; aspirational controls converted to descriptive where implemented.
- **Success criteria:** future features and remediations are auditable by default.
- **Risks:** adoption fatigue; exceptions become normal.
- **Dependencies:** Phases 1–4.

## Milestone checkpoints
- **M1 (end Phase 1):** constitution approved and exception log created.
- **M2 (end Phase 2):** P0 specs + acceptance criteria approved.
- **M3 (end Phase 3):** manifest/lock/traceability foundation verifiably working.
- **M4 (end Phase 4):** P0 gates pass; Critical risk posture demonstrably reduced.
- **M5 (end Phase 5):** spec-driven workflow operating on live changes.
