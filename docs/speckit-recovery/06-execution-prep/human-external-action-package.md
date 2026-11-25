# Human/External Action Package (2026-11-15)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Purpose | Make every human/external blocked item actionable with owners-to-confirm, decisions requested, evidence to collect, and ready-to-use templates/checklists |
| Status | **Draft; no approvals/decisions recorded** |
| Constraints | Evidence-based preparation only. No legal determinations, no fabricated approvals, no source/test/config changes, no shared-DB writes. |

## 0. How to use
1. Hold M1 review per `stakeholder-review-pack.md`, `m1-readiness-checklist.md`, `execution-sequence.md`.
2. Record outcomes in `m1-decision-log-template.md` and `decision-unknown-tracker.md`.
3. Assign owners and execute requests/checklists below; attach evidence links/paths and dates.
4. After required approvals/gates, convert `m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md` to traced execution artifacts.

## 1. M1 approvals and governance (human)

### 1.1 Constitution ratification request
- **Requested action:** Ratify or disposition all 14 principles / 95 rules and record authority/date.
- **Artifacts:** `../03-constitution/constitution-draft.md`, `constitution-disposition-and-exceptions.md`.
- **Capture in:** `m1-decision-log-template.md` §2, §6.

| Prompt for reviewers | Response fields |
|---|---|
| Ratify constitution as drafted, modified, deferred, or rejected (batch/per-rule as needed)? | Decision, authority, date, scope, notes |
| Are Descriptive vs Aspirational classifications accepted? | Decision + adjustments |
| What evidence is required before any Aspirational rule is treated as enforced? | Rule IDs, verification, owner |

### 1.2 Critical exception dispositions (EX-001..EX-005)
- **Requested action:** For each exception choose: approve time-bounded exception, require remediation, or mark resolved; provide compensating controls, owner, expiry/review date, authority.
- **Artifacts:** `constitution-disposition-and-exceptions.md`, `../04-migration/risk-register.md`.
- **Capture in:** `m1-decision-log-template.md` §3.

| ID | Related | Draft recommendation (not approved) | Decision requested | Compensating controls (if exception) | Owner | Expiry/review | Authority/date |
|---|---|---|---|---|---|---|---|
| EX-001 | `FR-UNI-01`, `NFR-PIT-02`, `RK-01` | Time-bounded; label outputs survivor-biased/non-decision-grade until RM-01 verified | Approve/Remediate/Resolve | e.g. PIT caveat labels, no promotion claims, RM-01 plan+date |  |  |  |
| EX-002 | `FR-DIV-07`, `RK-05/10` | Time-bounded; explicit adjustment/caveat labeling until RM-03/04 verified | Approve/Remediate/Resolve | e.g. basis labels, reconciliation plan |  |  |  |
| EX-003 | `NFR-PIT-01`, `RK-02` | Remediation plan required; no PIT filing-date compliance claim for affected logic | Approve/Remediate/Resolve | e.g. restrict affected use, filing-date remediation milestone |  |  |  |
| EX-004 | `NFR-PIT-02`, `RK-01` | Same posture as EX-001 | Approve/Remediate/Resolve |  |  |  |  |
| EX-005 | `NFR-PIT-03/04/05`, `RK-09` | Require simulation/caveat/as-of/fetch-time labeling per approved contracts | Approve/Remediate/Resolve | e.g. UI/report metadata requirements, interim labels |  |  |  |

## 2. External/policy decisions (DEC-001..DEC-008)

Record in `m1-decision-log-template.md` §4 and `decision-unknown-tracker.md`.

| ID | Decision requested | Suggested owner (confirm) | Needed by | Evidence/input | Draft recommendation (not approved) |
|---|---|---|---|---|---|
| DEC-001 | Provider licensing/terms for internal use, caching, redistribution, derived data (yfinance, FMP, SEC, OpenBB, others used) | Data Governance + Legal | M2/M4 | Completed `provider-terms-inventory-template.md`, ToS/API terms, redistribution/cache clauses, Unknowns recorded | Do not claim redistribution rights; restrict use per documented terms; record Unknown where terms unavailable |
| DEC-002 | Frozen holdout ownership, storage, access, freeze/eval protocol | Quant Research Lead | M2 | Holdout spec, access control, run ledger/manifest field | Define untouched holdout and access policy before any promotion-grade claim |
| DEC-003 | Acceptance-policy versioning and change-control authority/process | Quant Research + Governance | M2 | Policy ID/version scheme, effective date, manifest field, change approval flow | Version policy and include policy/version/hash in manifests |
| DEC-004 | Cost model and exposure-matched benchmark for published backtests | Quant Research Lead | M2 spec / M4 evidence | Trading/financing/cash assumptions, gross/net, benchmark definition | Specify comparable assumptions in spec before performance claims |
| DEC-005 | ML promotion gate ownership and evidence package (rule score remains default) | Model Owner/Quant Lead | M2 | Written gate, evidence package, production default confirmation | Keep `rule_scoring_v1` (or current rule default) until explicit promotion evidence approved |
| DEC-006 | Streamlit direct warehouse-read boundary: formalize exception or route via API/service | Architecture/Security Lead | M4/M5 | Allowed reads, credentials/roles, controls, threat/risk note | Document explicit boundary/exception with compensating controls; prefer service boundary if feasible |
| DEC-007 | `sql/silver_schema.sql` disposition and canonical schema declaration | Data/Engineering Lead | M2 | Runtime references, reconciliation with `sql/schema.sql`/migrations | Declare canonical schema source; archive or document non-runtime artifacts |
| DEC-008 | Dependency/lock strategy (tooling, hash policy, CI/Docker/local enforcement) | Platform/DevOps Lead | M2/M3 | Chosen lock format/tool, install modes, enforcement points | Adopt explicit lock/hash strategy enforced across local/CI/Docker |

## 3. UNK-004 — Reports Center UI/runtime confirmation (human in running UI)

- **Status:** code evidence and `reports-center-asof-contract-draft.md` prepared; Streamlit health reachable (`127.0.0.1:8501/_stcore/health`). Interactive content not verifiable headlessly.
- **Requested action:** complete `unk004-ui-verification-checklist.md` in a running non-prod/read-only environment and attach evidence (screenshots/notes) to tracker.
- **Output:** completed checklist + approved/annotated contract or implementation gap list.

## 4. UNK-005 — contract approval and project-path validation (human decision + controlled test)

- **Status:** isolated synthetic and actual-`DIVIDEND_UPSERT` tests completed (disposable DB) — see `unk005-isolated-batch-test-2026-11-15.md`, `unk005-actual-upsert-isolated-test-2026-11-15.md`.
- **Human decisions requested:**
  1. Conflict key/feed-evidence strategy (keep provider-only PK with defined supersession, include `feed` in key, or append-only evidence + curated projection).
  2. Deterministic in-batch pre-dedupe precedence (e.g. feed priority, retrieval time, completeness, declaration presence, amount basis).
  3. Date/field preservation rule (`COALESCE` for non-NULL dates/fields vs explicit versioned correction flow).
  4. Quarantine/reconciliation audit behavior for runtime corrections.
- **Controlled validation requested (after decision):** run actual loader batching/runtime path in **isolated project test DB/schema with rollback/teardown** (no shared DB writes). Record evidence in tracker.
- **Draft recommendation (not approved):** deterministic pre-dedupe, preserve existing non-NULL dates unless explicit audited correction, retain feed-level evidence/provenance.

## 5. UNK-001/002 — canonical basis decisions (human/quant/data)

- **Status:** read-only evidence advanced (`unk001-unk002-basis-analysis-2026-11-15.md`).
- **Decisions requested:**
  - `UNK-001`: canonical `raw.market_data.close`/adjusted semantics and required storage/compute/consumer contract (`FR-ADJ-01`).
  - `UNK-002`: per-provider/feed dividend amount and `adjusted_amount` basis, canonical field(s) for consumers, and reconciliation rules (`FR-DIV-08`).
- **Evidence to collect:** broader samples, provider documentation/terms where permitted, consumer impact list, M2 spec updates (`TSK-019/021`).

## 6. UNK-007 — external systems evidence requests (platform/SRE/governance/providers)

- **Status:** local/dev and repo-config evidence gathered (`unk007-local-systems-evidence-2026-11-15.md`); template `external-systems-inventory-template.md`.
- **Requests to send/complete:**

| Area | Question/evidence requested | Owner | Evidence format |
|---|---|---|---|
| Scheduler/orchestrator | What schedules nightly ETL and ops jobs per environment? run history, retry/alerting, access controls | Platform/SRE | Config ref, screenshots/export, runbook |
| Object/artifact store | Where are manifests/reports/artifacts stored? retention, immutability, encryption, access | Platform/Data Eng | Bucket/path policy, retention config |
| DB backup/restore | Backup frequency, encryption, retention, last **tested restore** date/result, RPO/RTO | DBA/Platform | Backup policy + restore test record |
| Secret management | How are DB/API/provider credentials injected/rotated? audit trail | Security/Platform | Secret manager policy/config ref (no values) |
| CI/CD | How are dependencies/locks enforced? artifact provenance, environment parity | DevOps | Pipeline config/ref, policy |
| Provider audit/terms | ToS/redistribution/cache terms and request/audit log availability for yfinance/FMP/SEC/OpenBB/others | Data Governance/Legal | Completed `provider-terms-inventory-template.md` entries |

## 7. UNK-003 — post-RM-01 comparison (blocked by design, human planning)

- **Status:** proxy evidence only; true delta blocked by RM-01 PIT membership reconstruction.
- **Requested action:** include RM-01 design/milestone in approved plan; after PIT-ready slice, assign owner/date to run read-only or isolated survivor-vs-PIT comparison per `validation-plans-unk001-007.md` and record materiality.

## 8. Ready-to-send request templates

### 8.1 M1 review meeting request
> Subject: M1 Review — SpecKit Recovery Ratification, Exceptions (EX-001..05), and Decisions (DEC-001..08)
>
> Please review `docs/speckit-recovery/06-execution-prep/stakeholder-review-pack.md` and `m1-readiness-checklist.md`. In the session we need: (1) constitution disposition/authority, (2) EX-001..05 dispositions with controls/owner/expiry, (3) owners/dates/evidence for DEC-001..08 and UNK-001..07, (4) go/no-go to convert P0 M2 drafts. Outcomes will be recorded in `m1-decision-log-template.md`.

### 8.2 Evidence request (UNK-007 / DEC-001)
> Subject: Evidence request — external systems inventory and provider terms (SpecKit recovery M1/M2)
>
> Please complete relevant rows in `docs/speckit-recovery/06-execution-prep/external-systems-inventory-template.md` and `provider-terms-inventory-template.md` with owner, environment, control/retention summary, and evidence reference (no secret values). Mark unknowns explicitly with follow-up owner/date.

### 8.3 UNK-004 UI verification request
> Subject: UI verification — Reports Center as-of/fetch-time (UNK-004)
>
> Please complete `docs/speckit-recovery/06-execution-prep/unk004-ui-verification-checklist.md` in a running non-prod/read-only environment and attach screenshots/notes to `decision-unknown-tracker.md`.

## 9. Completion criteria for clearing human/external blockers
- [ ] M1 decision log completed with authority/date and no unbounded Critical exceptions.
- [ ] DEC-001..08 recorded with owners/dates/evidence (or explicit accepted unknown/deferral).
- [ ] UNK-004 checklist completed with runtime evidence.
- [ ] UNK-005 contract decisions recorded and isolated project-path validation evidence attached.
- [ ] UNK-001/002 canonical basis decisions recorded.
- [ ] UNK-007 inventory completed for relevant environments (or gaps explicitly owned).
- [ ] UNK-003 scheduled/executed after RM-01 readiness.
