# Decision and Unknown Tracker (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Draft; M1/CI approval and evidence requested but not supplied** |
| Prepared M1 packet | `m1-ratification-packet-2026-11-18.md`; recommendations only; approval requested from approver/team; no approval recorded |

## 1. External/policy decisions (blocking or gating)
| ID | Decision needed | Why it matters | Traceability | Proposed owner | Needed by | Status | Notes / evidence to collect |
|---|---|---|---|---|---|---|---|
| DEC-001 | Provider licensing/terms for internal use, caching, redistribution and derived data (yfinance, FMP, SEC, OpenBB, others) | Determines lawful use/distribution and provider onboarding controls | `NFR-GOV-03`, `DG-11`, `DC-04`, `RK-13`, `TSK-004` | Product/Data Governance + Legal | 2026-12-31 | Proposed deferral; pending approval | Inventory due 2026-12-31; blocks distribution claims |
| DEC-002 | Frozen holdout ownership, storage, access and evaluation protocol | Required for decision-grade promotion evidence | `FR-EVAL-03`, `CM-01`, `DC-02`, `RK-04`, `TSK-003` | Quant Research Lead | 2026-12-15 | Proposed outcome; pending approval | Define untouched holdout, freeze point, run ledger |
| DEC-003 | Acceptance-policy versioning authority and change-control process (including post-hoc invalidation) | Prevents policy drift and reused-holdout bias | `FR-EVAL-03`, `NFR-GOV-01`, `CM-01/02`, `RK-04`, `TSK-003/008` | Quant Research + Governance | 2026-12-15 | Proposed outcome; pending approval | Version policy; post-hoc changes invalidate evidence |
| DEC-004 | Cost model and exposure-matched benchmark definition for published backtests | Required before performance claims are comparable | `FR-BT-03/04`, `DC-10`, `RK-04`, `TSK-003/018` | Quant Research Lead | 2026-12-15 | Proposed outcome; pending approval | Gross/net, costs, cash treatment, exposure-matched benchmark required |
| DEC-005 | ML promotion gate ownership and evidence package | Keeps production ranking rule-based until explicitly promoted | `FR-SIG-01`, `FR-EVAL-02`, `DC-01/02`, `TSK-003` | Model Owner/Quant Lead | 2026-11-18 | Ratified | `rule_scoring_v1` remains production default until explicit promotion |
| DEC-006 | Streamlit direct warehouse-read boundary: formalize exception or route through API/service layer | Affects separation/security/maintainability posture | `PE-25`, `NFR-SEC-02`, `RK-15`, `TSK-027` | Architecture/Security Lead | 2026-12-31 | Proposed deferral; pending approval | Document allowed reads, credentials, and controls |
| DEC-007 | `sql/silver_schema.sql` disposition (archive non-runtime or adopt/document) and canonical schema declaration | Reduces schema ambiguity | `PE-21/23`, `ES-06`, `RK-12`, `TSK-006/007` | Data/Engineering Lead | 2026-12-15 | Proposed outcome; pending approval | `sql/schema.sql` is runtime canonical; mark silver schema non-runtime |
| DEC-008 | Dependency/lock management approach (tooling, hash policy, CI/Docker/local install mode) | Needed for reproducible runtime | `NFR-REPRO-01/02`, `ES-09`, `RK-06`, `TSK-026` | Platform/DevOps Lead | 2026-12-15 | Proposed/local strategy: exact pins plus lock-file SHA-256 (no per-package hashes); pending approval | Enforced in CI/Docker; manifest identity extended; clean-environment parity pending |

## 1A. Critical exception register (EX-001..EX-005)

M1 recorded the following time-bounded dispositions on 2026-11-18. Closure evidence remains due by 2026-12-31; no exception is closed.

| ID | Requirement / risk | Disposition | Compensating control | Owner | Expiry / review | Authority / date | Status |
|---|---|---|---|---|---|---|---|
| EX-001 | FR-UNI-01, NFR-PIT-02, RK-01 | Time-bounded exception | Label historical outputs survivorship-biased; prohibit promotion claims; close via RM-01 PIT delta | Data/Quant Lead | 2026-12-31 | Governance Lead (role), 2026-11-18 | Proposed; pending approval |
| EX-002 | FR-DIV-07, RK-02 | Time-bounded exception | Adjustment-basis caveat labeling; close via RM-03/RM-04 evidence | Data Engineering + Quant | 2026-12-31 | Governance Lead (role), 2026-11-18 | Proposed; pending approval |
| EX-003 | NFR-PIT-01, RK-02 | Remediation required | No filing-time compliance claim until timing gates pass | Data Engineering Lead | 2026-12-31 | Governance Lead (role), 2026-11-18 | Proposed; pending approval |
| EX-004 | NFR-PIT-02, RK-01 | Time-bounded exception | Treat affected timing evidence as non-decision-grade | Data/QA Lead | 2026-12-31 | Governance Lead (role), 2026-11-18 | Proposed; pending approval |
| EX-005 | NFR-PIT-03/04/05, RK-09 | Time-bounded exception | Store/display as-of, fetch time, and simulation caveats | App/Data Lead | 2026-12-31 | Governance Lead (role), 2026-11-18 | Proposed; pending approval |

## 2. Technical unknowns requiring targeted validation
| ID | Unknown | Validation action | Evidence source / traceability | Proposed owner | Needed by | Status |
|---|---|---|---|---|---|---|
| UNK-001 | Raw close basis: are stored `raw.market_data.close` values split-adjusted/unadjusted consistently (`adjusted_close` 100% NULL)? | Sampled security/date audit vs provider events; document canonical basis | `FA-U01`, `FR-ADJ-01`, `PA-P01/02`, `RK-05`, `TSK-021` | Data Engineering/Quant | 2026-12-15 | Assigned; canonical close-basis decision due 2026-12-15 |
| UNK-002 | Dividend amount basis: are Yahoo/OpenBB/FMP amounts split-adjusted per event/security as assumed? | Reconcile sample events against raw provider evidence and split factors | `FA-U03`, `FR-DIV-08`, `PA-D14`, `RK-05/10`, `TSK-019/021` | Data Engineering | 2026-12-15 | Assigned; canonical dividend amount-basis decision due 2026-12-15 |
| UNK-003 | Survivorship magnitude (survivor-vs-PIT delta) | Build or simulate PIT membership slice and compare universe/returns/performance | `BI-01`, `FR-UNI-01`, `RK-01`, `TSK-016` | Quant/Data Lead | 2026-12-31 | Assigned; survivor-vs-PIT comparison due 2026-12-31 |
| UNK-004 | Reports Center as-of labeling behavior in UI | Read/verify report rendering and parameterization; add acceptance test if needed | `BI-37`, `FR-REP-02`, `RK-09`, `TSK-011/024` | App/UI Lead | 2026-12-15 | Assigned; UI/runtime as-of confirmation due 2026-12-15 |
| UNK-005 | Duplicate-key dividend batch behavior (raise vs silent keep) | Safe isolated test/inspection of loader + DB constraint behavior; document contract | `DA-21`, `FR-DIV-01`, `RK-10`, `TSK-019` | Data Engineering | 2026-12-15 | Assigned; batch/key/date contract approval and isolated validation due 2026-12-15 |
| UNK-006 | Migration ledger discrepancy (104 migration files vs applied max 106) | Reconcile `sql/migrations/`, ledger/history, and deployed state; document authoritative source | `PE-23`, `CM-03`, `RK-12`, `TSK-007` | Data/Platform Lead | M2 | Resolved (repo+DB read-only evidence, 2026-11-15); V0045 gap undocumented |
| UNK-007 | External scheduler/object-store/backup/restore and provider audit-log state | Inventory external systems, retention, access controls, and recovery evidence | `RK-13`, `NFR-REPRO-04` (scope limit), `TSK-004` | Platform/SRE + Data Governance | 2026-12-31 | Assigned; external systems/recovery evidence due 2026-12-31 |

## 3. Validation log
| Date | IDs | Outcome | Evidence |
|---|---|---|---|
| 2026-11-15 | UNK-004, UNK-005, UNK-006 | UNK-006 resolved (repo+DB ledger reconcile: 104 files + baseline V0001 = 105 rows, missing 45); UNK-004/005 repo-evidence gathered, runtime/UI/write-test confirmation pending | `repo-validations-2026-11-15.md` |
| 2026-11-15 | UNK-001, UNK-002 | Partial DB evidence gathered: `adjusted_close` 0/9,823,774 with split-adjacent sample; provider/feed amount vs adjusted_amount semantics vary (yfinance adjusted NULL, fmp mixed, SEC_XBRL adjusted NULL). Canonical bases unresolved | `repo-validations-2026-11-15.md` |

## 4. Validation log (continued)
| Date | IDs | Outcome | Evidence |
|---|---|---|---|
| 2026-11-15 | DEC-001, NFR-SEC-03, TSK-004/005 | Drafted provider-terms and secret inventory templates (metadata-only, no values); completion pending stakeholder/legal/owner input | `provider-terms-inventory-template.md`, `secret-inventory-template.md` |

## 5. Immediate validation plan (next executable checks)
| Priority | Check | Output | Traceability |
|---|---|---|---|
| P0 | Document historical rationale for V0045 numbering gap (if needed) | Governance note (optional) | `TSK-007`, `PE-23` |
| P0 | Review/approve Reports Center as-of/fetch-time storage and historical selection contract; confirm UI/runtime behavior | Approved contract + UI/runtime confirmation for UNK-004 | `BI-37`, `FR-REP-02`, `TSK-024` |
| P0 | Approve dividend batch/key/date-integrity contract and run safe isolated duplicate-key verification | Approved contract + controlled test/design note for UNK-005/DA-21 | `DA-21`, `FR-DIV-01`, `TSK-019` |
| P1 | Sample adjustment/basis evidence for representative securities/events | Analysis note/update to UNK-001/002 | `FA-U01/U03`, `TSK-021` |
| P1 | Complete provider/secret inventory templates with owners, evidence and decisions | Stakeholder/legal/owner completion of drafted templates | `DEC-001`, `TSK-004/005` |
| P1 | Complete external systems inventory and recovery evidence | Stakeholder/platform completion for UNK-007 | `external-systems-inventory-template.md`, `validation-plans-unk001-007.md` |
| P1 | Execute/record remaining UNK validation plans per owner assignment | Evidence notes and tracker updates for UNK-001..005,007 | `validation-plans-unk001-007.md` |
