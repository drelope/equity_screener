# M1 Decision and Approval Log (Template)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation / M1 gate |
| Date | 2026-11-15 (template created) |
| Status | **Template; no approvals recorded** |
| Purpose | Record formal approvals, dispositions, and decision outcomes required for M1 exit |

> **Instructions:** Complete during/after stakeholder review. Attach or link evidence artifacts. Do not backfill approvals without authority/date.
>
> **Prepared review packet (2026-11-18):** `m1-ratification-packet-2026-11-18.md` and `project-constitution-ratification-draft.md` provide review-ready recommendations. They are not approvals; every field below remains Pending until a named authority and date are recorded.

## 1. Review session record

| Field | Entry |
|---|---|
| Session date/time |  |
| Facilitator |  |
| Participants (name/role) |  |
| Artifacts reviewed | `stakeholder-review-pack.md`, `../05-speckit/executive-summary.md`, `constitution-disposition-and-exceptions.md`, `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md`, others: |
| Scope confirmed (yes/no + notes) |  |
| Go/No-Go to proceed to M2 drafting (pending/yes/no) | Pending |

## 2. Constitution ratification

| Item | Decision (ratified/modified/deferred/rejected) | Authority | Date | Evidence/notes |
|---|---|---|---|---|
| 14 principles (PE-01..30 basis) | Pending |  |  |  |
| 95-rule disposition batch (see `constitution-disposition-and-exceptions.md`) | Pending |  |  |  |
| Descriptive vs Aspirational classification accepted/adjusted | Pending |  |  |  |

## 3. Critical exception dispositions (EX-001..EX-005)

| ID | Related reqs | Disposition (approve exception / require remediation / time-bounded / resolved) | Compensating controls | Owner | Expiry/review date | Authority/date | Evidence |
|---|---|---|---|---|---|---|---|
| EX-001 | FR-UNI-01, NFR-PIT-02, RK-01 | Pending |  |  |  |  |  |
| EX-002 | FR-DIV-07, RK-05/10 | Pending |  |  |  |  |  |
| EX-003 | NFR-PIT-01, RK-02 | Pending |  |  |  |  |  |
| EX-004 | NFR-PIT-02, RK-01 | Pending |  |  |  |  |  |
| EX-005 | NFR-PIT-03/04/05, RK-09 | Pending |  |  |  |  |  |

## 4. Decision outcomes (DEC-001..DEC-008)

| ID | Decision outcome | Owner | Due date | Evidence/reference | Status |
|---|---|---|---|---|---|
| DEC-001 |  |  |  | `provider-terms-inventory-template.md` | Pending |
| DEC-002 |  |  |  |  | Pending |
| DEC-003 |  |  |  |  | Pending |
| DEC-004 |  |  |  |  | Pending |
| DEC-005 |  |  |  |  | Pending |
| DEC-006 |  |  |  |  | Pending |
| DEC-007 |  |  |  |  | Pending |
| DEC-008 |  |  |  |  | Pending |

## 5. Validation assignments (UNK-001..UNK-007)

| ID | Assigned owner | Due date | Approved plan/reference | Status |
|---|---|---|---|---|
| UNK-001 |  |  | `validation-plans-unk001-007.md` | Pending |
| UNK-002 |  |  | `validation-plans-unk001-007.md` | Pending |
| UNK-003 |  |  | `validation-plans-unk001-007.md` (blocked by RM-01) | Pending |
| UNK-004 |  |  | `reports-center-asof-contract-draft.md`, `validation-plans-unk001-007.md` | Pending |
| UNK-005 |  |  | `dividend-batch-key-contract-draft.md`, `validation-plans-unk001-007.md` | Pending |
| UNK-006 |  |  | Resolved (optional rationale) | Resolved |
| UNK-007 |  |  | `external-systems-inventory-template.md`, `validation-plans-unk001-007.md` | Pending |

## 6. M1 exit confirmation

| Criterion | Met? | Evidence |
|---|---|---|
| Constitution disposition recorded with authority/date | Pending |  |
| EX-001..EX-005 resolved or time-bounded with controls/expiry | Pending |  |
| DEC-002/003/004/008 sufficient for M2 drafting | Pending |  |
| UNK-001..007 owners/dates/plans assigned | Pending |  |
| Approved to convert P0 M2 drafts to traced execution artifacts | Pending |  |

**M1 status:** Pending
**Authorized by / date:**
**Next review date:**


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
