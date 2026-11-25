# Step 1 — M1 Governance Gate (Prepared)

| Field | Value |
|---|---|
| Recommendation | Unblock governance before implementation |
| Status | **Prepared; human approval/authority required** |
| Primary artifacts | `../06-execution-prep/m1-readiness-checklist.md`, `../06-execution-prep/m1-decision-log-template.md`, `../06-execution-prep/constitution-disposition-and-exceptions.md`, `../06-execution-prep/decision-unknown-tracker.md`, `../06-execution-prep/stakeholder-review-pack.md` |

## 1. Objective
Obtain an approved governance baseline: constitution disposition, Critical exception decisions (`EX-001..05`), and ownership/decisions for `DEC-001..08` and `UNK-001..07`, with go/no-go for M2 P0 conversion.

## 2. Executed preparation (done)
- [x] Readiness checklist and decision/approval log templates prepared.
- [x] 95-rule disposition draft and Critical exception register prepared.
- [x] Draft recommendations prepared (evidence-based, explicitly non-approved) in decision log / action package.
- [x] P0 M2 drafts and contracts prepared (`RM-01..07`, `P0-TSK-001..010`).

## 3. Actions requiring human execution
| # | Action | Output | Owner (confirm) |
|---|---|---|---|
| 1.1 | Hold M1 review (use stakeholder review pack and checklist) | Attendance/scope notes | Governance/Program Lead |
| 1.2 | Ratify/disposition 14 principles and 95 rules | Signed disposition record (authority/date) | Governance/Engineering Lead |
| 1.3 | Disposition `EX-001..05` | Each resolved or time-bounded with compensating controls, owner, expiry/review, authority | Data/Quant/App/Governance leads as assigned |
| 1.4 | Decide/assign `DEC-001..08` (min `DEC-002/003/004/008` for M2) | Decision log entries with owners/dates/evidence | Named decision owners |
| 1.5 | Assign `UNK-001..07` validation owners/plans | Tracker updates with due dates and approved plans | Program/Tech Lead |
| 1.6 | Record M1 exit go/no-go | Approval to convert M2 P0 drafts | Approval authority |

## 4. Draft resolutions (recommendations, not decisions)

| Item | Draft recommendation | Interim compensating control |
|---|---|---|
| EX-001 / EX-004 (`FR-UNI-01`, `NFR-PIT-02`) | Time-bounded exception tied to RM-01 delivery; no decision-grade claim | Label outputs survivor-biased; exclude from promotion evidence |
| EX-002 (`FR-DIV-07`) | Time-bounded exception tied to RM-03/04; basis reconciliation required | Label adjustment basis/caveats on affected outputs |
| EX-003 (`NFR-PIT-01`) | Remediation required for filing/availability-date semantics | Restrict/label PIT-sensitive analyses; no filing-date compliance claim |
| EX-005 (`NFR-PIT-03/04/05`) | Require as-of/fetch-time/simulation/caveat metadata and labels | Apply contract draft labels in UI/reports when implemented; treat current as non-compliant until verified |
| DEC-002/003/004/005 | Freeze holdout, version acceptance policy, define cost/exposure-matched benchmark, keep rule score default until promoted | No promotion/performance claims without these artifacts |
| DEC-008 | Adopt explicit lock/hash enforcement (local/CI/Docker) | Mark runs non-reproducible until enforced |

## 5. Exit criteria
- M1 checklist sections A–D satisfied with evidence/authority recorded.
- No unbounded Critical exception.
- `DEC-002/003/004/008` sufficient to approve M2 drafting/conversion.
- `UNK-001..07` assigned with validation plans.
