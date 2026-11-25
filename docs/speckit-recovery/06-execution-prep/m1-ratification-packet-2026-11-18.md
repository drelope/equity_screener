# M1 Ratification Packet (Prepared — Not Approved)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M1 gate |
| Prepared | 2026-11-18 |
| Status | **Prepared for external approval; no M1/CI evidence supplied** |
| Purpose | Give reviewers a single packet for M1 constitution ratification, EX/DEC/UNK disposition, and go/no-go authority |
| Approval rule | No approval recorded. Named approver/date and external CI evidence requested from approver/team but not supplied. |

## 1. Review package

| Artifact | Review purpose |
|---|---|
| [project-constitution-ratification-draft.md](project-constitution-ratification-draft.md) | Proposed project constitution derived from recovered principles and rules |
| [constitution-disposition-and-exceptions.md](constitution-disposition-and-exceptions.md) | 95-rule disposition matrix and five Critical exception proposals |
| [decision-unknown-tracker.md](decision-unknown-tracker.md) | DEC-001..008 and UNK-001..007 ownership/status baseline |
| [m1-decision-log-template.md](m1-decision-log-template.md) | Prepared approval record; all fields Pending |
| [m1-readiness-checklist.md](m1-readiness-checklist.md) | M1 exit checklist; all items Pending |
| [stakeholder-review-pack.md](stakeholder-review-pack.md) | Review scope and requested outputs |
| [../../../specs/001-p0-recovery/spec.md](../../../specs/001-p0-recovery/spec.md) | Approved P0 feature specification |
| [../../../specs/001-p0-recovery/plan.md](../../../specs/001-p0-recovery/plan.md) | Approved P0 plan with M1 implementation blocker |

## 2. Proposed review sequence

1. Confirm the 14 recovered principles and whether each is Descriptive, Aspirational, Modified, Deferred, or Rejected.
2. Confirm the proposed treatment of the 95 rules: ratify Descriptive rules as non-regression controls; adopt Aspirational rules as enforced targets with verification, without reclassifying them as Descriptive before evidence exists.
3. Dispose EX-001..EX-005: approve, require remediation, or set a time-bounded exception with owner, compensating control, and expiry.
4. Decide DEC-001..DEC-008; at minimum DEC-002/003/004/008 must be sufficient for P0 execution.
5. Assign owners, due dates, and approved plans for UNK-001..UNK-007.
6. Record the M1 go/no-go, authority, date, and evidence links in `m1-decision-log-template.md`.
7. Only after step 6 and recorded external approval may task T003 be cleared; do not treat the current draft constitution as ratified.

## 3. Proposed disposition summary

### Constitution

| Item | Prepared recommendation | Approval status |
|---|---|---|
| 14 principles | Accept the recovered register as the review basis; mark 3 Practised and 11 Partial as recorded, not certified | Recorded by user direction, 2026-11-18 |
| 30 Descriptive rules | Ratify as existing non-regression controls where CI/code evidence still holds | Recorded by user direction, 2026-11-18 |
| 65 Aspirational rules | Adopt as target rules; enforce progressively; do not reclassify without verification evidence | Recorded by user direction, 2026-11-18 |
| AI-IOS document | Remain non-normative future reference; no principles imported from it | Recorded by user direction, 2026-11-18 |

### Critical exceptions

| ID | Prepared recommendation | Approval status |
|---|---|---|
| EX-001 | Time-bounded exception until RM-01 membership/PIT evidence is verified; prohibit promotion claims meanwhile | Recorded by user direction, 2026-11-18 |
| EX-002 | Time-bounded exception with adjustment-basis caveat labeling until RM-03/RM-04 verification | Recorded by user direction, 2026-11-18 |
| EX-003 | Require remediation; no PIT filing-date compliance claim until timing gates pass | Recorded by user direction, 2026-11-18 |
| EX-004 | Same control posture as EX-001; treat affected timing evidence as non-decision-grade | Recorded by user direction, 2026-11-18 |
| EX-005 | Require stored as-of/fetch-time labels and simulation caveats in report contracts | Recorded by user direction, 2026-11-18 |

### Decisions required for P0 execution

| ID | Minimum decision needed | Prepared recommendation | Approval status |
|---|---|---|---|
| DEC-002 | Holdout owner/storage/access/freeze protocol | Name a Quant Research owner; define frozen snapshot and access before promotion evidence is accepted | Recorded by user direction, 2026-11-18 |
| DEC-003 | Acceptance-policy versioning/change control | Version policy before evaluation; hash it into manifests; post-hoc changes invalidate evidence | Recorded by user direction, 2026-11-18 |
| DEC-004 | Cost model and exposure-matched benchmark | Require gross/net, cost assumptions, and matched comparison before comparable backtest claims | Recorded by user direction, 2026-11-18 |
| DEC-008 | Dependency/lock strategy | Ratify lock format and local/CI/Docker enforcement before T031 | Recorded by user direction, 2026-11-18 |
| DEC-005 | ML promotion gate | Confirm `rule_scoring_v1` remains production default until explicit approval | Recorded by user direction, 2026-11-18 |
| DEC-001/006/007 | Provider terms, Streamlit DB boundary, canonical schema | Resolve or explicitly defer with owner/date; record in tracker | Recorded by user direction, 2026-11-18 |

## 4. Evidence currently available

- Constitution draft and 95-rule disposition: `../03-constitution/`, `constitution-disposition-and-exceptions.md`.
- Draft M1 log with proposals and blank approval fields: `m1-decision-log-template.md`.
- DEC/UNK tracker with proposed owners and evidence sources: `decision-unknown-tracker.md`.
- P0 implementation/validation bundle: `../08-implementation-validation/`.
- SpecKit spec/plan/tasks/analysis state: `../../../specs/001-p0-recovery/`.

## 5. Recorded outcome and residual non-claims

- Recommendations are prepared in `m1-decision-log-template.md`; the named approver/date and external CI evidence have been requested but not supplied.
- No M1 approval, ratification, or CI status is recorded.
- No GO is recorded; merge, release, promotion, and cutover remain blocked.
- It does not close AC-P0 acceptance criteria, authorize migration promotion, or authorize production cutover.
- Evidence due 2026-12-15/2026-12-31 remains pending.
- AI-IOS remains a non-normative requirement source.
