# M1 Decision and Approval Log (Template)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M1 gate |
| Date | 2026-11-15 (template created) |
| Status | **Owner-supplied inputs recorded; no effective M1 approval or CI status** |
| Purpose | Record formal approvals, dispositions, and decision outcomes required for M1 exit |

> **Instructions:** Complete during/after stakeholder review. Attach or link evidence artifacts. Do not backfill approvals without authority/date.
>
> **Preparation basis:** Recommendations were prepared in `m1-ratification-packet-2026-11-18.md` and `project-constitution-ratification-draft.md`. Owner-supplied inputs: approver `Andre`, date `11/19/2025`, and repository URL `https://github.com/drelope/equity_screener`. The supplied date predates the current workspace date `2026-11-19`, and the URL is a repository URL rather than a CI run URL. These inputs are recorded but not treated as effective approval or CI evidence.

## 1. Review session record

| Field | Entry |
|---|---|
| Session date/time | Pending external review |
| Facilitator | Pending |
| Participants (name/role) | Owner-supplied approver name: Andre; formal review status Pending |
| Artifacts reviewed | `stakeholder-review-pack.md`, `../05-speckit/executive-summary.md`, `constitution-disposition-and-exceptions.md`, `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md`, others: |
| Scope confirmed (yes/no + notes) | Pending formal confirmation; owner-supplied identity/URL recorded only |
| Go/No-Go to proceed to M2 drafting (pending/yes/no) | Pending; no approval evidence supplied |

## 2. Constitution ratification

| Item | Decision (approve/modify/defer/reject) | Authority | Date | Evidence/notes |
|---|---|---|---|---|
| 14 principles (PE-01..30 basis) | Pending review: 3 Practised, 11 Partial recorded as evidence snapshot | Pending | Pending | No approval recorded |
| 95-rule disposition batch (see `constitution-disposition-and-exceptions.md`) | Pending review: 30 Descriptive, 65 Aspirational proposed | Pending | Pending | No approval recorded |
| Descriptive vs Aspirational classification accepted/adjusted | Pending review | Pending | Pending | Separate classifications retained |

## 3. Critical exception dispositions (EX-001..EX-005)

| ID | Related reqs | Disposition (approve exception / require remediation / time-bounded / resolved) | Compensating controls | Owner | Expiry/review date | Authority/date | Evidence |
|---|---|---|---|---|---|---|---|
| EX-001 | FR-UNI-01, NFR-PIT-02, RK-01 | Time-bounded exception | Survivorship-biased label; prohibit promotion claims; RM-01 PIT delta | Data/Quant Lead | 2026-12-31 | Pending | Close via RM-01 evidence |
| EX-002 | FR-DIV-07, RK-05/10 | Time-bounded exception | Adjustment-basis caveat labeling; RM-03/RM-04 verification | Data Engineering + Quant | 2026-12-31 | Pending | Close via evidence |
| EX-003 | NFR-PIT-01, RK-02 | Remediation required | No filing-time compliance claim until timing gates pass | Data Engineering Lead | 2026-12-31 | Pending | RM-02/RM-07 |
| EX-004 | NFR-PIT-02, RK-01 | Time-bounded exception | Treat affected timing evidence as non-decision-grade | Data/QA Lead | 2026-12-31 | Pending | Same posture as EX-001 |
| EX-005 | NFR-PIT-03/04/05, RK-09 | Time-bounded exception | Store/display as-of/fetch time and simulation caveats | App/Data Lead | 2026-12-31 | Pending | Contract required |

## 4. Decision outcomes (DEC-001..DEC-008)

| ID | Decision outcome | Owner | Due date | Evidence/reference | Status |
|---|---|---|---|---|---|
| DEC-001 | Defer; inventory due 2026-12-31; blocks distribution claims | Data Governance + Legal | 2026-12-31 | `provider-terms-inventory-template.md` | Proposed deferral; pending approval |
| DEC-002 | Quant Research Lead owns frozen holdout/access/freeze protocol | Quant Research Lead | 2026-12-15 | `promotion-policy-template.json` | Proposed outcome; pending approval |
| DEC-003 | Versioned policy; post-hoc changes invalidate evidence | Quant Research + Governance | 2026-12-15 | `promotion-policy-template.json` | Proposed outcome; pending approval |
| DEC-004 | Gross/net, costs, cash treatment, exposure-matched benchmark required | Quant Research Lead | 2026-12-15 | `promotion-gate-contract-draft.md` | Proposed outcome; pending approval |
| DEC-005 | `rule_scoring_v1` remains production default until explicit promotion | Model Owner/Quant Lead | 2026-11-18 | `constitution-disposition-and-exceptions.md` | Pending approval |
| DEC-006 | Defer Streamlit DB boundary decision | Architecture/Security Lead | 2026-12-31 | `decision-unknown-tracker.md` | Proposed deferral; pending approval |
| DEC-007 | `sql/schema.sql` is runtime canonical; mark silver schema non-runtime | Data/Engineering Lead | 2026-12-15 | `decision-unknown-tracker.md` | Proposed outcome; pending approval |
| DEC-008 | Approve lock/hash strategy with local/CI/Docker enforcement | Platform/DevOps Lead | 2026-12-15 | `reproducibility-lock-policy-draft.md` | Proposed outcome; pending approval |

## 5. Validation assignments (UNK-001..UNK-007)

| ID | Assigned owner | Due date | Approved plan/reference | Status |
|---|---|---|---|---|
| UNK-001 | Data Engineering/Quant | 2026-12-15 | `validation-plans-unk001-007.md` | Assigned |
| UNK-002 | Data Engineering | 2026-12-15 | `validation-plans-unk001-007.md` | Assigned |
| UNK-003 | Quant/Data Lead | 2026-12-31 | `validation-plans-unk001-007.md` (blocked by RM-01) | Assigned |
| UNK-004 | App/UI Lead | 2026-12-15 | `reports-center-asof-contract-draft.md`, `validation-plans-unk001-007.md` | Assigned |
| UNK-005 | Data Engineering | 2026-12-15 | `dividend-batch-key-contract-draft.md`, `validation-plans-unk001-007.md` | Assigned |
| UNK-006 | Data/Platform Lead | 2026-12-15 | Resolved (optional rationale) | Resolved |
| UNK-007 | Platform/SRE + Data Governance | 2026-12-31 | `external-systems-inventory-template.md`, `validation-plans-unk001-007.md` | Assigned |

## 6. M1 exit confirmation

| Criterion | Met? | Evidence |
|---|---|---|
| Constitution disposition recorded with authority/date | Met | Role-based authority, 2026-11-18 |
| EX-001..EX-005 resolved or time-bounded with controls/expiry | Met | Time-bounded to 2026-12-31 with controls |
| DEC-002/003/004/008 sufficient for M2 drafting | Met | Outcomes recorded; evidence due 2026-12-15 |
| UNK-001..007 owners/dates/plans assigned | Met | Assigned in section 5 |
| Approved to convert P0 M2 drafts to traced execution artifacts | Pending | Owner-supplied identity/date/URL recorded; no effective approval or CI run evidence |

**M1 status:** Pending formal approval; merge and release blocked
**Owner-supplied identity/date:** Andre / 11/19/2025 (not effective; date confirmation required)
**Owner-supplied URL:** https://github.com/drelope/equity_screener (repository URL, not a CI run URL)
**Authorized by / date:** Not recorded
**Next review date:** Pending


## 7. Draft recommendations (evidence-based, not approved)

> These are preparation notes to accelerate review; they are **not decisions or approvals**.

| ID | Draft recommendation | Rationale / evidence | Required approver |
|---|---|---|---|
| EX-001 | Time-bounded exception with explicit "survivor-biased, not decision-grade" labeling until RM-01 verified | `FR-UNI-01` Missing; inactive securities/scores/features exist but no `delisted_date`/PIT membership (`UNK-003` proxy) | Data/Quant + Governance |
| EX-002 | Time-bounded exception; require explicit split-adjustment/caveat labeling on outputs until RM-03/RM-04 verified | `FR-DIV-07` Missing; `adjusted_close` NULL and dividend basis heterogeneity observed (`UNK-001/002`) | Data Eng + Quant |
| EX-003 | Require remediation plan; do not claim PIT filing-date compliance for affected effective-date logic | `NFR-PIT-01` Partial/Critical (`FR-DIV-03` Missing, `FR-FEAT-01` risk) | Data Eng + Governance |
| EX-004 | Same control posture as EX-001 (survivorship/PIT universe) | `NFR-PIT-02` Partial/Critical | Data/Quant + Governance |
| EX-005 | Require UI/report labels for simulation/caveats/as-of-fetch-time in M2/P0 contracts | `NFR-PIT-03/04/05` Partial; Reports Center current behavior evidence gathered (`UNK-004`) | Product/Quant + App Lead |
| DEC-002 | Define frozen holdout + access policy before any promotion-grade evaluation claim | `FR-EVAL-03` Missing | Quant Research Lead |
| DEC-003 | Version acceptance policy and include policy/version hash in manifests | `NFR-GOV-01` Partial, `RK-04` | Quant Research + Governance |
| DEC-004 | Specify gross/net/cost and exposure-matched benchmark in spec before comparable backtest claims | `FR-BT-03/04/05` gaps | Quant Research Lead |
| DEC-008 | Adopt explicit lock/hash strategy enforced in CI/Docker/local workflow | `NFR-REPRO-01/02` Partial | Platform/DevOps Lead |
| UNK-005 | Approve deterministic in-batch pre-dedupe precedence + `COALESCE`/date-preservation + feed-evidence strategy; validate in isolated project test DB | Isolated tests show CardinalityViolation (multi-values same-key) and NULL overwrite (`unk005-isolated-batch-test-2026-11-15.md`) | Data Engineering Lead |
