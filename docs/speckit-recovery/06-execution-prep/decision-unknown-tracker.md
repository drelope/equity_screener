# Decision and Unknown Tracker (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Draft; decisions pending stakeholder/owner input** |
| Prepared M1 packet | `m1-ratification-packet-2026-11-18.md` contains prepared recommendations; no decision or ownership status is changed by that packet |

## 1. External/policy decisions (blocking or gating)
| ID | Decision needed | Why it matters | Traceability | Proposed owner | Needed by | Status | Notes / evidence to collect |
|---|---|---|---|---|---|---|---|
| DEC-001 | Provider licensing/terms for internal use, caching, redistribution and derived data (yfinance, FMP, SEC, OpenBB, others) | Determines lawful use/distribution and provider onboarding controls | `NFR-GOV-03`, `DG-11`, `DC-04`, `RK-13`, `TSK-004` | Product/Data Governance + Legal (proposed) | M2/M4 | Pending | Collect provider ToS, API terms, redistribution/cache clauses; record Unknowns explicitly |
| DEC-002 | Frozen holdout ownership, storage, access and evaluation protocol | Required for decision-grade promotion evidence | `FR-EVAL-03`, `CM-01`, `DC-02`, `RK-04`, `TSK-003` | Quant Research Lead (proposed) | M2 | Pending | Define untouched holdout, freeze point, run ledger |
| DEC-003 | Acceptance-policy versioning authority and change-control process (including post-hoc invalidation) | Prevents policy drift and reused-holdout bias | `FR-EVAL-03`, `NFR-GOV-01`, `CM-01/02`, `RK-04`, `TSK-003/008` | Quant Research + Governance (proposed) | M2 | Pending | Policy ID/version, criteria, effective date, manifest field |
| DEC-004 | Cost model and exposure-matched benchmark definition for published backtests | Required before performance claims are comparable | `FR-BT-03/04`, `DC-10`, `RK-04`, `TSK-003/018` | Quant Research Lead (proposed) | M2 (spec), M4 (evidence) | Pending | Trading/financing/cash assumptions; gross/net benchmark spec |
| DEC-005 | ML promotion gate ownership and evidence package | Keeps production ranking rule-based until explicitly promoted | `FR-SIG-01`, `FR-EVAL-02`, `DC-01/02`, `TSK-003` | Model Owner/Quant Lead (proposed) | M2 | Pending | Confirm rule_scoring_v1 remains production default |
| DEC-006 | Streamlit direct warehouse-read boundary: formalize exception or route through API/service layer | Affects separation/security/maintainability posture | `PE-25`, `NFR-SEC-02`, `RK-15`, `TSK-027` | Architecture/Security Lead (proposed) | M4/M5 | Pending | Document allowed reads, credentials, and controls |
| DEC-007 | `sql/silver_schema.sql` disposition (archive non-runtime or adopt/document) and canonical schema declaration | Reduces schema ambiguity | `PE-21/23`, `ES-06`, `RK-12`, `TSK-006/007` | Data/Engineering Lead (proposed) | M2 | Pending | Confirm runtime references; reconcile with canonical schema |
| DEC-008 | Dependency/lock management approach (tooling, hash policy, CI/Docker/local install mode) | Needed for reproducible runtime | `NFR-REPRO-01/02`, `ES-09`, `RK-06`, `TSK-026` | Platform/DevOps Lead (proposed) | M2/M3 | Pending | Choose lock format and enforcement points |

## 2. Technical unknowns requiring targeted validation
| ID | Unknown | Validation action | Evidence source / traceability | Proposed owner | Needed by | Status |
|---|---|---|---|---|---|---|
| UNK-001 | Raw close basis: are stored `raw.market_data.close` values split-adjusted/unadjusted consistently (`adjusted_close` 100% NULL)? | Sampled security/date audit vs provider events; document canonical basis | `FA-U01`, `FR-ADJ-01`, `PA-P01/02`, `RK-05`, `TSK-021` | Data Engineering/Quant | M2/M3 | Evidence advanced (2026-11-15): split-adjacent samples show non-ratio-adjusted close behavior with NULL adjusted_close; broader confirmation + canonical decision pending |
| UNK-002 | Dividend amount basis: are Yahoo/OpenBB/FMP amounts split-adjusted per event/security as assumed? | Reconcile sample events against raw provider evidence and split factors | `FA-U03`, `FR-DIV-08`, `PA-D14`, `RK-05/10`, `TSK-019/021` | Data Engineering | M2/M3 | Evidence advanced (2026-11-15): provider/feed heterogeneity and cross-provider amount differences documented; canonical basis decision pending |
| UNK-003 | Survivorship magnitude (survivor-vs-PIT delta) | Build or simulate PIT membership slice and compare universe/returns/performance | `BI-01`, `FR-UNI-01`, `RK-01`, `TSK-016` | Quant/Data Lead | M4 | Proxy evidence gathered (2026-11-15); magnitude unresolved, blocked by RM-01 |
| UNK-004 | Reports Center as-of labeling behavior in UI | Read/verify report rendering and parameterization; add acceptance test if needed | `BI-37`, `FR-REP-02`, `RK-09`, `TSK-011/024` | App/UI Lead | M2 | Evidence + contract draft prepared (2026-11-15); Streamlit service health reachable (127.0.0.1:8501) but interactive UI/runtime confirmation pending |
| UNK-005 | Duplicate-key dividend batch behavior (raise vs silent keep) | Safe isolated test/inspection of loader + DB constraint behavior; document contract | `DA-21`, `FR-DIV-01`, `RK-10`, `TSK-019` | Data Engineering | M2 | Evidence advanced (2026-11-15): contract draft + isolated synthetic and actual-`DIVIDEND_UPSERT` disposable-DB tests confirm multi-values CardinalityViolation, NULL date overwrite, and feed-collision-at-PK; precedence/key/feed-evidence decision and project-loader-path validation pending |
| UNK-006 | Migration ledger discrepancy (104 migration files vs applied max 106) | Reconcile `sql/migrations/`, ledger/history, and deployed state; document authoritative source | `PE-23`, `CM-03`, `RK-12`, `TSK-007` | Data/Platform Lead | M2 | Resolved (repo+DB read-only evidence, 2026-11-15); V0045 gap undocumented |
| UNK-007 | External scheduler/object-store/backup/restore and provider audit-log state | Inventory external systems, retention, access controls, and recovery evidence | `RK-13`, `NFR-REPRO-04` (scope limit), `TSK-004` | Platform/SRE + Data Governance | M3 | Partially addressed (2026-11-15): local/dev and repo-config evidence gathered; prod/external scheduler/object-store/backup-restore/provider-audit evidence pending |

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
