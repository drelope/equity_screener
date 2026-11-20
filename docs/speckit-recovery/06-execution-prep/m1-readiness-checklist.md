# M1 Readiness Checklist (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Prepared for external approval; no M1 approval or CI evidence supplied** |
| Purpose | Gate-check for M1 completion (constitution ratification, Critical exceptions, decision ownership) |
| Traceability | `RM-01..07`, `TSK-001..003`, `DEC-001..008`, `EX-001..005`, `UNK-001..007` |
| Prepared review packet | `m1-ratification-packet-2026-11-18.md` and `project-constitution-ratification-draft.md`; recommendations only; approval requested from approver/team |

## A. Constitution and exceptions (required for M1)

| # | Item | Owner | Due | Evidence / output | Status |
|---|---|---|---|---|---|
| M1-01 | Review and ratify 14 principles / 95 rules in `../03-constitution/constitution-draft.md` and `constitution-disposition-and-exceptions.md` | Governance/Engineering Lead | Pending | Prepared in `m1-decision-log-template.md`; `project-constitution-ratification-draft.md` | Pending |
| M1-02 | Disposition `EX-001` (`FR-UNI-01` survivorship/PIT universe) with compensating controls, owner, expiry/review date | Data/Quant + Governance | Pending | Proposed time-bounded exception in `m1-decision-log-template.md` | Pending |
| M1-03 | Disposition `EX-002` (`FR-DIV-07` ex-div adjustment policy) | Data Engineering + Quant | Pending | Proposed time-bounded exception with caveat labeling | Pending |
| M1-04 | Disposition `EX-003` (`NFR-PIT-01` effective vs filing timing) | Data Engineering + Governance | Pending | Proposed remediation requirement; no filing-time claim | Pending |
| M1-05 | Disposition `EX-004` (`NFR-PIT-02` survivorship controls) | Data/Quant + Governance | Pending | Proposed time-bounded exception; non-decision-grade evidence | Pending |
| M1-06 | Disposition `EX-005` (`NFR-PIT-03/04/05` simulation/caveat/labeling) | Product/Quant + App Lead | Pending | Proposed time-bounded exception; as-of/fetch/caveat labels required | Pending |
| M1-07 | Record formal approval authority, date, and scope of ratification | Governance Lead (role) | Pending | Prepared in `m1-decision-log-template.md` | Pending |

## B. Decision ownership and evidence (minimum for M2 drafting gate)

| # | Decision | Minimum outcome for M2 start | Owner | Due | Status |
|---|---|---|---|---|---|
| M1-D1 | `DEC-002` frozen holdout ownership/storage/protocol | Named owner, storage location, access policy, freeze/eval protocol draft | Quant Research Lead | Pending | Proposed; pending approval |
| M1-D2 | `DEC-003` acceptance-policy versioning/change control | Policy ID/version scheme, change authority, manifest field spec | Quant Research + Governance | Pending | Proposed; pending approval |
| M1-D3 | `DEC-004` cost model & exposure-matched benchmark | Spec-level assumptions and required evidence fields (even if values provisional) | Quant Research Lead | Pending | Proposed; pending approval |
| M1-D4 | `DEC-008` dependency/lock strategy | Chosen tooling/lock format and enforcement points (local/CI/Docker) | Platform/DevOps Lead | Pending | Proposed; pending approval |
| M1-D5 | `DEC-001` provider terms/licensing | Inventory started with ToS/redistribution/cache posture per provider; unknowns recorded | Data Governance + Legal | Pending | Proposed deferral; pending approval |
| M1-D6 | `DEC-005` ML promotion gate | Written confirmation: rule score remains production default; promotion evidence owner | Model Owner/Quant Lead | Pending | Proposed; pending approval |
| M1-D7 | `DEC-006` Streamlit DB boundary | Exception-or-route decision documented | Architecture/Security Lead | Pending | Proposed deferral; pending approval |
| M1-D8 | `DEC-007` `sql/silver_schema.sql` / schema canonicalization | Disposition and canonical source decision | Data/Engineering Lead | Pending | Proposed; pending approval |

## C. Validation readiness (assignments and plans)

| # | Item | Owner | Due | Status |
|---|---|---|---|---|
| M1-V1 | Assign owners/dates for `UNK-001..007` in `decision-unknown-tracker.md` | Program/Tech Lead | Pending | Prepared; see M1 log |
| M1-V2 | Approve/execute controlled validation plans in `validation-plans-unk001-007.md` (safe, read-only or isolated as specified) | Data/App/Platform Leads | Pending | Prepared; pending approval |
| M1-V3 | Confirm external-systems inventory scope and responders for `UNK-007` (`external-systems-inventory-template.md`) | Platform/SRE + Data Governance | Pending | Prepared; pending approval |

## D. M1 exit criteria (proposed)

- [ ] M1-01..M1-07 completed with recorded evidence/approvals.
- [ ] `EX-001..EX-005` each resolved or time-bounded with compensating controls and expiry.
- [ ] `DEC-002/003/004/008` sufficiently specified to approve P0 M2 drafts.
- [ ] `UNK-001..007` have owners, due dates, and approved validation plans.
- [ ] No GO recorded; M1 approval pending; merge and release blocked.

## E. Notes / constraints
- This checklist does not claim implementation, verification, or promotion-grade readiness.
- Any deferred Critical/High control must carry explicit compensating controls and review/expiry.
- Descriptive and aspirational constitution rules remain separated unless evidence supports reclassification.
