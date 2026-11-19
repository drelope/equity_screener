# M1 Readiness Checklist (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Draft; all items Pending unless evidence recorded** |
| Purpose | Gate-check for M1 completion (constitution ratification, Critical exceptions, decision ownership) |
| Traceability | `RM-01..07`, `TSK-001..003`, `DEC-001..008`, `EX-001..005`, `UNK-001..007` |
| Prepared review packet | `m1-ratification-packet-2026-11-18.md` and `project-constitution-ratification-draft.md` (recommendations only; no approvals recorded) |

## A. Constitution and exceptions (required for M1)

| # | Item | Owner | Due | Evidence / output | Status |
|---|---|---|---|---|---|
| M1-01 | Review and ratify 14 principles / 95 rules in `../03-constitution/constitution-draft.md` and `constitution-disposition-and-exceptions.md` | Governance/Engineering Lead |  | Signed disposition record (Adopt/Modify/Defer/Reject per rule or approved batch) | Pending |
| M1-02 | Disposition `EX-001` (`FR-UNI-01` survivorship/PIT universe) with compensating controls, owner, expiry/review date | Data/Quant + Governance |  | Approved exception or remediation commitment | Pending |
| M1-03 | Disposition `EX-002` (`FR-DIV-07` ex-div adjustment policy) | Data Engineering + Quant |  | Approved exception/remediation + interim labeling policy | Pending |
| M1-04 | Disposition `EX-003` (`NFR-PIT-01` effective vs filing timing) | Data Engineering + Governance |  | Approved exception/remediation | Pending |
| M1-05 | Disposition `EX-004` (`NFR-PIT-02` survivorship controls) | Data/Quant + Governance |  | Approved exception/remediation | Pending |
| M1-06 | Disposition `EX-005` (`NFR-PIT-03/04/05` simulation/caveat/labeling) | Product/Quant + App Lead |  | Approved exception/remediation + UI/labeling requirements | Pending |
| M1-07 | Record formal approval authority, date, and scope of ratification | Governance Lead |  | Approval note linked from this package | Pending |

## B. Decision ownership and evidence (minimum for M2 drafting gate)

| # | Decision | Minimum outcome for M2 start | Owner | Due | Status |
|---|---|---|---|---|---|
| M1-D1 | `DEC-002` frozen holdout ownership/storage/protocol | Named owner, storage location, access policy, freeze/eval protocol draft | Quant Research Lead |  | Pending |
| M1-D2 | `DEC-003` acceptance-policy versioning/change control | Policy ID/version scheme, change authority, manifest field spec | Quant Research + Governance |  | Pending |
| M1-D3 | `DEC-004` cost model & exposure-matched benchmark | Spec-level assumptions and required evidence fields (even if values provisional) | Quant Research Lead |  | Pending |
| M1-D4 | `DEC-008` dependency/lock strategy | Chosen tooling/lock format and enforcement points (local/CI/Docker) | Platform/DevOps Lead |  | Pending |
| M1-D5 | `DEC-001` provider terms/licensing | Inventory started with ToS/redistribution/cache posture per provider; unknowns recorded | Data Governance + Legal |  | Pending |
| M1-D6 | `DEC-005` ML promotion gate | Written confirmation: rule score remains production default; promotion evidence owner | Model Owner/Quant Lead |  | Pending |
| M1-D7 | `DEC-006` Streamlit DB boundary | Exception-or-route decision documented | Architecture/Security Lead |  | Pending |
| M1-D8 | `DEC-007` `sql/silver_schema.sql` / schema canonicalization | Disposition and canonical source decision | Data/Engineering Lead |  | Pending |

## C. Validation readiness (assignments and plans)

| # | Item | Owner | Due | Status |
|---|---|---|---|---|
| M1-V1 | Assign owners/dates for `UNK-001..007` in `decision-unknown-tracker.md` | Program/Tech Lead |  | Pending |
| M1-V2 | Approve/execute controlled validation plans in `validation-plans-unk001-007.md` (safe, read-only or isolated as specified) | Data/App/Platform Leads |  | Pending |
| M1-V3 | Confirm external-systems inventory scope and responders for `UNK-007` (`external-systems-inventory-template.md`) | Platform/SRE + Data Governance |  | Pending |

## D. M1 exit criteria (proposed)

- [ ] M1-01..M1-07 completed with recorded evidence/approvals.
- [ ] `EX-001..EX-005` each resolved or time-bounded with compensating controls and expiry.
- [ ] `DEC-002/003/004/008` sufficiently specified to approve P0 M2 drafts.
- [ ] `UNK-001..007` have owners, due dates, and approved validation plans.
- [ ] Go/no-go recorded to convert `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` into traced Spec Kit execution artifacts.

## E. Notes / constraints
- This checklist does not claim implementation, verification, or promotion-grade readiness.
- Any deferred Critical/High control must carry explicit compensating controls and review/expiry.
- Descriptive and aspirational constitution rules remain separated unless evidence supports reclassification.
