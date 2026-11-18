# Stage 4 Compliance Scorecard

| Field | Value |
|---|---|
| Stage | 4 — Synthesis and migration |
| Date | 2026-11-15 |
| Scale | 0–5 (0 absent, 1 ad hoc, 2 partial, 3 defined, 4 managed/measured, 5 controlled/reproducible) |

## Scores

| Domain | Score | Justification | Key evidence |
|---|---:|---|---|
| CRISP-DM process compliance | 2.8 / 5 | Business/Data Understanding, Preparation, Modeling and Deployment show working implemented flows, but Evaluation is weak (2/5) due to non-reproducible promotion evidence, unmatched benchmark/no costs, and mutable/stale artifacts; cross-cutting PIT gaps reduce overall defensibility. | Stage 2 `crisp-dm-matrix.md` (3,3,3,3,2,3; avg 2.83), `PE-14/15`, `FR-EVAL-03`, `FR-BT-03..05` |
| Research governance | 2.0 / 5 | Some controls exist (fail-closed gate, prediction versions, audit tables, quarantine/freshness), but policy/holdout discipline, immutable decision evidence, run manifests and complete lineage are missing; provider licensing unknown. | `NFR-GOV-01 Partial`, `NFR-GOV-02 Implemented`, `NFR-GOV-03 Unknown`, `PE-03/04/07/08/10/12/15/30`, `BI-05/06`, `DA-02/09/10/16/18` |
| Reproducibility | 1.5 / 5 | Container/CI/runtime baselines and some pins exist at HEAD, but worktree is unpinned with no lock and installed drift; runs/artifacts lack code/env/input/policy manifests and mutable stores overwrite evidence. | `NFR-REPRO-01..04` (3 Partial, 1 Missing), `PE-05/06/04/12`, `DA-09..11,17,18`, broken dry-run (`TG-01`) |
| Production readiness | 2.5 / 5 | Meaningful operational/security strengths (API auth/rate limits, ops allowlist, read-only explorer, non-root containers, advisory lock, migration preflight, quality/freshness checks) but recent nightly failures, no resume/root-cause capture, PIT/correctness gaps, weak test gates and stale warehouse reduce readiness. | `NFR-SEC-01..03`, `NFR-REL-01..02`, `NFR-SCALE-01`, `PE-16/17/26/27`, audit nightly failures, 84-req status 18/53/12/1, Critical `FR-UNI-01,FR-DIV-07,NFR-PIT-01..02` |

## Interpretation
- **Strongest areas:** security/operational controls and modular separation (practised controls exist and should be preserved).
- **Weakest areas:** reproducibility and research governance, primarily due to missing run identity/manifests, mutable evidence stores, and unenforced PIT/determinism contracts.
- **Gate implication:** do not treat current evaluation artifacts as promotion-grade until RM-01..RM-07 materially close Critical/High gaps.

## Trend target (post-remediation)
| Domain | Current | Target after Phase 4 | Condition |
|---|---:|---:|---|
| CRISP-DM process compliance | 2.8 | >=3.5 | Evaluation and PIT controls verified with manifests and matched benchmarks |
| Research governance | 2.0 | >=3.5 | Policy/holdout/run lineage enforced; provider terms resolved |
| Reproducibility | 1.5 | >=3.5 | Hashed lock, manifests, immutable artifacts, clean replay passes |
| Production readiness | 2.5 | >=3.5 | PIT/correctness fixes, reliability hardening, blocking test/release gates |
