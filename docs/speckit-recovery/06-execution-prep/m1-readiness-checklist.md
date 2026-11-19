# M1 Readiness Checklist (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Recorded 2026-11-18 by user direction; see `m1-decision-log-template.md`** |
| Purpose | Gate-check for M1 completion (constitution ratification, Critical exceptions, decision ownership) |
| Traceability | `RM-01..07`, `TSK-001..003`, `DEC-001..008`, `EX-001..005`, `UNK-001..007` |
| Prepared review packet | `m1-ratification-packet-2026-11-18.md` and `project-constitution-ratification-draft.md`; adopted by user direction; named individual substitution pending |

## A. Constitution and exceptions (required for M1)

| # | Item | Owner | Due | Evidence / output | Status |
|---|---|---|---|---|---|
| M1-01 | Review and ratify 14 principles / 95 rules in `../03-constitution/constitution-draft.md` and `constitution-disposition-and-exceptions.md` | Governance/Engineering Lead | 2026-11-18 | `m1-decision-log-template.md`; `project-constitution-ratification-draft.md` | Met |
| M1-02 | Disposition `EX-001` (`FR-UNI-01` survivorship/PIT universe) with compensating controls, owner, expiry/review date | Data/Quant + Governance | 2026-12-31 | Time-bounded exception in `m1-decision-log-template.md` | Met |
| M1-03 | Disposition `EX-002` (`FR-DIV-07` ex-div adjustment policy) | Data Engineering + Quant | 2026-12-31 | Time-bounded exception with caveat labeling | Met |
| M1-04 | Disposition `EX-003` (`NFR-PIT-01` effective vs filing timing) | Data Engineering + Governance | 2026-12-31 | Remediation required; no filing-time claim | Met |
| M1-05 | Disposition `EX-004` (`NFR-PIT-02` survivorship controls) | Data/Quant + Governance | 2026-12-31 | Time-bounded exception; non-decision-grade evidence | Met |
| M1-06 | Disposition `EX-005` (`NFR-PIT-03/04/05` simulation/caveat/labeling) | Product/Quant + App Lead | 2026-12-31 | Time-bounded exception; as-of/fetch/caveat labels required | Met |
| M1-07 | Record formal approval authority, date, and scope of ratification | Governance Lead (role) | 2026-11-18 | `m1-decision-log-template.md`; named individual substitution pending | Met |

## B. Decision ownership and evidence (minimum for M2 drafting gate)

| # | Decision | Minimum outcome for M2 start | Owner | Due | Status |
|---|---|---|---|---|---|
| M1-D1 | `DEC-002` frozen holdout ownership/storage/protocol | Named owner, storage location, access policy, freeze/eval protocol draft | Quant Research Lead | 2026-12-15 | Met as decision; evidence pending |
| M1-D2 | `DEC-003` acceptance-policy versioning/change control | Policy ID/version scheme, change authority, manifest field spec | Quant Research + Governance | 2026-12-15 | Met as decision; evidence pending |
| M1-D3 | `DEC-004` cost model & exposure-matched benchmark | Spec-level assumptions and required evidence fields (even if values provisional) | Quant Research Lead | 2026-12-15 | Met as decision; evidence pending |
| M1-D4 | `DEC-008` dependency/lock strategy | Chosen tooling/lock format and enforcement points (local/CI/Docker) | Platform/DevOps Lead | 2026-12-15 | Met as decision; evidence pending |
| M1-D5 | `DEC-001` provider terms/licensing | Inventory started with ToS/redistribution/cache posture per provider; unknowns recorded | Data Governance + Legal | 2026-12-31 | Deferred with due date |
| M1-D6 | `DEC-005` ML promotion gate | Written confirmation: rule score remains production default; promotion evidence owner | Model Owner/Quant Lead | 2026-11-18 | Met |
| M1-D7 | `DEC-006` Streamlit DB boundary | Exception-or-route decision documented | Architecture/Security Lead | 2026-12-31 | Deferred with due date |
| M1-D8 | `DEC-007` `sql/silver_schema.sql` / schema canonicalization | Disposition and canonical source decision | Data/Engineering Lead | 2026-12-15 | Met as decision; evidence pending |

## C. Validation readiness (assignments and plans)

| # | Item | Owner | Due | Status |
|---|---|---|---|---|
| M1-V1 | Assign owners/dates for `UNK-001..007` in `decision-unknown-tracker.md` | Program/Tech Lead | 2026-12-15 | Met; see M1 log |
| M1-V2 | Approve/execute controlled validation plans in `validation-plans-unk001-007.md` (safe, read-only or isolated as specified) | Data/App/Platform Leads | 2026-12-31 | Met as plan approval; execution evidence pending |
| M1-V3 | Confirm external-systems inventory scope and responders for `UNK-007` (`external-systems-inventory-template.md`) | Platform/SRE + Data Governance | 2026-12-31 | Met as assignment; evidence pending |

## D. M1 exit criteria (proposed)

- [x] M1-01..M1-07 completed with recorded evidence/approvals.
- [x] `EX-001..EX-005` each resolved or time-bounded with compensating controls and expiry.
- [x] `DEC-002/003/004/008` sufficiently specified to approve P0 M2 drafts.
- [x] `UNK-001..007` have owners, due dates, and approved validation plans.
- [x] Conditional GO recorded to convert `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` into traced Spec Kit execution artifacts.

## E. Notes / constraints
- This checklist does not claim implementation, verification, or promotion-grade readiness.
- Any deferred Critical/High control must carry explicit compensating controls and review/expiry.
- Descriptive and aspirational constitution rules remain separated unless evidence supports reclassification.
