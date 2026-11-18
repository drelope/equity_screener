# Execution Sequence (Proposed)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation handoff |
| Date | 2026-11-15 |
| Status | **Draft proposal; sequencing subject to stakeholder approval** |
| Constraints | Read-only recovery baseline; no implementation/promotion claims; no shared-DB writes or source/test/config changes in this preparation |

## Phase 1 — M1 gate (immediate, blocking)
**Goal:** establish approved governance baseline before M2 drafting/execution.

| Step | Actions | Inputs | Outputs/evidence | Exit criteria |
|---|---|---|---|---|
| 1.1 | Conduct review | `stakeholder-review-pack.md`, `../05-speckit/executive-summary.md`, `../03-constitution/constitution-draft.md` | Review notes/attendees | Scope/priorities acknowledged |
| 1.2 | Ratify constitution | `constitution-disposition-and-exceptions.md`, `m1-readiness-checklist.md` (M1-01/07) | Approved disposition record (Adopt/Modify/Defer/Reject) | 95 rules dispositioned with authority/date |
| 1.3 | Finalize Critical exceptions | `constitution-disposition-and-exceptions.md` (`EX-001..05`), `../04-migration/risk-register.md` | Approved/resolved exceptions with compensating controls, owner, expiry/review | No unbounded Critical exception |
| 1.4 | Assign decision/unknown ownership | `decision-unknown-tracker.md`, `m1-readiness-checklist.md` (M1-V1) | Owners, due dates, evidence targets for `DEC-001..08`, `UNK-001..007` | All items assigned or explicitly deferred |

**Gate:** M1 exit criteria in `m1-readiness-checklist.md` Section D.

## Phase 2 — M2 drafting readiness (parallel after 1.4)
**Goal:** make P0 scope spec-ready with approved inputs.

| Step | Actions | Inputs | Outputs/evidence | Depends on |
|---|---|---|---|---|
| 2.1 | Finalize minimum M2 decisions | `DEC-002,003,004,008` in tracker; `m2-specify-p0.md` assumptions | Recorded decisions/spec inputs | 1.4 owners assigned |
| 2.2 | Approve P0 contracts | `reports-center-asof-contract-draft.md`, `dividend-batch-key-contract-draft.md` | Approved/annotated contracts | 1.2/1.3 context |
| 2.3 | Start/complete inventories | `provider-terms-inventory-template.md`, `secret-inventory-template.md`, `external-systems-inventory-template.md` | Completed templates with evidence refs/unknowns | 1.4, legal/platform input for DEC-001/UNK-007 |
| 2.4 | Review P0 draft package | `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` | Approved M2 baseline and go/no-go to convert | 2.1, 2.2 |

## Phase 3 — Remaining validations (parallel, safe/controlled)
**Goal:** reduce evidence gaps before or during M2 conversion/implementation planning.

| Step | Actions | Inputs | Outputs/evidence | Safety/constraints |
|---|---|---|---|---|
| 3.1 | UNK-004 runtime confirmation | `reports-center-asof-contract-draft.md`, `validation-plans-unk001-007.md` | UI/runtime observation note (as-of/fetch-time, historical selection/download) | Read-only/non-prod environment |
| 3.2 | UNK-005 duplicate-key test/design | `dividend-batch-key-contract-draft.md`, `repo-validations-2026-11-15.md` | Isolated test/design note for `DA-21` batch behavior and precedence | **Isolated DB or transaction rollback only; no shared DB writes** |
| 3.3 | UNK-001/002 basis reconciliation | `repo-validations-2026-11-15.md`, DB/provider evidence | Provider/feed/adjustment basis matrix and canonicalization decisions | Read-only analysis |
| 3.4 | UNK-007 external evidence | `external-systems-inventory-template.md` | Scheduler/object-store/backup/restore/provider-audit evidence | Human/operational access; metadata only |
| 3.5 | UNK-006 rationale (optional) | Migration history/governance records if available | V0045 gap note | Docs-only |

## Phase 4 — M2 conversion and traced execution setup
**Goal:** convert approved drafts into execution artifacts with gates.

| Step | Actions | Inputs | Outputs/evidence | Depends on |
|---|---|---|---|---|
| 4.1 | Convert P0 package | Approved `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` | Traced Spec Kit/execution artifacts for `RM-01..07`, `P0-TSK-001..010` | Phase 1 gate + 2.4 |
| 4.2 | Wire acceptance/RTM gates | `AC-P0-01..11`, `QG-01..07`, `../02-requirements/rtm.md` expectations | RTM update plan and verification checklist per task | 4.1 |
| 4.3 | Plan implementation sequencing | Task dependencies in `m2-tasks-p0.md` | Sprint/PR breakdown, owners, test strategy | 4.1, 3.x evidence where available |

## Phase 5 — Post-design / implementation-dependent work
**Goal:** complete items that require design or remediation to exist.

| Step | Actions | Inputs | Outputs/evidence | Blocker |
|---|---|---|---|---|
| 5.1 | UNK-003 survivor-vs-PIT delta | RM-01 PIT membership design/data, `validation-plans-unk001-007.md` | Reproducible comparison report with materiality | Blocked until RM-01 readiness |
| 5.2 | M3+ execution | RM-08..13 roadmap/tasks | Verified implementation evidence and updated RTM/statuses | Prior gates and approvals |

## Suggested parallelization
- **Can run in parallel:** 2.1, 2.2, 2.3 (as owners available); 3.1, 3.3, 3.4 (independent evidence tracks); 3.2 only in isolated environment.
- **Must serialize:** 1.2/1.3 before final M1 exit; 2.4 before 4.1; 5.1 after RM-01 design/data.

## Risk controls
- Treat all Partial/Missing as unverified until task-level evidence exists.
- Record every approval, exception, and validation outcome in tracker/log artifacts with dates and evidence refs.
- Do not claim promotion-grade readiness or execute source/test/config changes within recovery preparation scope.
