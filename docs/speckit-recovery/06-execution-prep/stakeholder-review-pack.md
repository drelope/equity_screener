# Stakeholder Review Pack (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Purpose | Enable review/approval of recovered baseline and P0 execution inputs without claiming decisions already made |
| Status | **Draft for review** |

## 1. Review scope
Please review and disposition the following artifacts:
| Artifact | Review focus | Decision requested |
|---|---|---|
| `../05-speckit/executive-summary.md` | Top findings, scorecard, top 5 risks, first 30 days | Confirm priority narrative and urgency |
| `../05-speckit/specify-draft.md` | Problem, objectives, scope, FR/NFR summaries, acceptance criteria, assumptions/constraints | Confirm modernization scope and non-goals |
| `../05-speckit/plan-draft.md` | Architecture/inventory, workstreams, metrics, milestones M1–M5 | Confirm delivery structure and milestone targets |
| `../05-speckit/tasks-draft.md` | Ordered backlog `TSK-001..028` | Confirm P0/P1 sequencing and ownership candidates |
| `constitution-disposition-and-exceptions.md` | 95-rule disposition table + Critical exception register | Ratify/adopt/modify/defer rules; approve or revise exception proposals |
| `decision-unknown-tracker.md` | External decisions and technical unknowns | Assign owners, due dates, and evidence sources |
| `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` | P0 Spec Kit-ready execution slice (`RM-01..07`) | Approve as M2 drafting baseline |

## 2. Baseline to acknowledge
- Snapshot: `2026-11-15`, repo `d748cea`; read-only recovery, no source/test/config changes.
- Requirements: **84** (53 FR, 31 NFR) — **18 Implemented, 53 Partial, 12 Missing, 1 Unknown**.
- Principles: 14 assessed — **3 Practised, 11 Partial** (`PE-01..30`).
- Constitution draft: **95 rules** — **30 Descriptive, 65 Aspirational**.
- Risks: **15** (`RK-01..15`), including 4 Critical: `RK-01` survivorship/PIT universe, `RK-02` leakage/timing defaults, `RK-03` mutable decision evidence, `RK-04` non-decision-grade evaluation.
- Readiness: **Conditional/Partial**. Not promotion-grade until P0 foundations are verified.

## 3. Decisions required (summary)
| ID | Decision | Why blocking | Proposed owner |
|---|---|---|---|
| DEC-001 | Provider terms/licensing and redistribution posture | `NFR-GOV-03` Unknown; affects ingestion/distribution controls | Product/Data Governance + Legal |
| DEC-002 | Frozen holdout ownership/storage/protocol | Promotion evidence cannot be decision-grade (`FR-EVAL-03`) | Quant Research Lead |
| DEC-003 | Acceptance-policy versioning/change control | Prevents policy drift/reused-holdout bias (`NFR-GOV-01`) | Quant Research + Governance |
| DEC-004 | Cost model and exposure-matched benchmark | Required for comparable backtests (`FR-BT-03/04`) | Quant Research Lead |
| DEC-005 | ML promotion gate ownership (rule score remains production default) | Preserves current production contract (`FR-SIG-01`) | Model Owner/Quant Lead |
| DEC-008 | Dependency/lock strategy across local/CI/Docker | Required for reproducibility (`NFR-REPRO-01/02`) | Platform/DevOps Lead |

## 4. Critical exceptions requiring explicit disposition (M1)
`FR-UNI-01`, `FR-DIV-07`, `NFR-PIT-01`, `NFR-PIT-02` must be **resolved or time-bounded** with compensating controls, owner, expiry/review date, and approval record. Draft proposals are in `constitution-disposition-and-exceptions.md` (all **Pending**).

## 5. P0 execution slice recommended for M2 approval
- **Scope:** `RM-01..RM-07` / `TSK-001..003,008..011,014,016,017,018,020,022,023,026`.
- **Outcome:** PIT integrity foundations, immutable run-keyed evidence/manifests, reproducible runtime, and blocking verification gates specified and planned with acceptance criteria.
- **Non-goal:** claiming implementation complete or promotion-grade readiness before verification evidence exists.

## 6. Review outputs requested
1. Approved/annotated constitution disposition (including Critical exceptions).
2. Decision log with owners, due dates, and evidence artifacts for DEC-001..008.
3. Validation assignments for UNK-001..007.
4. Go/no-go to proceed with M2 Spec Kit drafting on P0 scope (`m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md`).
5. Named exceptions list and compensating controls for any deferred Critical/High risk.

## 7. Constraints and caveats
- No source, test, or config changes are made by this preparation package.
- Drafts do not treat Partial/Missing controls as implemented; descriptive and aspirational rules remain separated.
- External legal/policy decisions and out-of-repo system states cannot be resolved from repository evidence alone.
