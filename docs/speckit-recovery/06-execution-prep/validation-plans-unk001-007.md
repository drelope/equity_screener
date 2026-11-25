# Remaining Validation Plans — UNK-001..UNK-007 (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Draft plans; execution pending approval/environment** |
| Purpose | Define concrete, safe validation steps and evidence outputs for unresolved/partial unknowns |

## Summary

| ID | Current status | Plan type | Environment/safety | Primary evidence output |
|---|---|---|---|---|
| UNK-001 | Partial evidence | Read-only sample audit + spec reconciliation | Read-only DB/repo/provider docs | Basis analysis note + contract decision input |
| UNK-002 | Partial evidence | Read-only sample audit + spec reconciliation | Read-only DB/repo/provider docs | Basis analysis note + contract decision input |
| UNK-003 | Proxy evidence, blocked | Comparative analysis after PIT design | Read-only or isolated recompute per RM-01 | Survivor-vs-PIT delta report |
| UNK-004 | Evidence + contract draft | UI/runtime confirmation + acceptance criteria | Running app (non-prod), read-only data | Runtime evidence + approved as-of/fetch-time contract |
| UNK-005 | Evidence + contract draft | Isolated/transactional duplicate-key test + design decision | **Isolated sandbox/transaction rollback only** (no shared DB writes) | Test/design note for `DA-21` + approved batch contract |
| UNK-006 | Resolved | Optional rationale note | Repo/docs only | V0045 gap note (optional) |
| UNK-007 | Outside scope | External inventory/interviews/evidence collection | Human/operational access | Completed external systems inventory |

## UNK-001 — Raw close / adjusted_close basis (`FA-U01`, `FR-ADJ-01`, `RK-05`)

- **Known:** `raw.market_data.adjusted_close` 0/9,823,774 non-null; sampled split-adjacent prices show raw close discontinuity with NULL adjusted_close.
- **Validation steps:**
  1. Select representative securities across split/dividend-heavy histories (include pre/post 2026 split sample and older events).
  2. Read-only compare stored `close` sequences around known `raw.corporate_actions` split effective dates and expected ratio-adjusted continuity.
  3. Cross-check provider metadata/documentation available in-repo or approved external sources for returned price basis.
  4. Document canonical basis assumption for `FR-ADJ-01` and required schema/loader/consumer changes in M2 spec.
- **Acceptance/evidence:** analysis note with sample table, concluded/declared canonical basis (or explicit unresolved decision), impacted consumers (`PA-P01/02`, features, BT).

## UNK-002 — Dividend amount / adjusted_amount basis (`FA-U03`, `FR-DIV-08`, `RK-05/10`)

- **Known:** heterogeneous semantics (yfinance 176,396 `adjusted_amount` NULL; SEC_XBRL 126,453 NULL; FMP 20,783 non-null with 268 amount!=adjusted_amount; 307,046 rows with >=1 null date). Same-date OPENBB/SEC_XBRL samples differ in amount/adjusted fields.
- **Validation steps:**
  1. Sample events by provider/feed and by cases where `amount != adjusted_amount` or adjusted is NULL/non-NULL.
  2. Read-only reconcile against stored SEC filing-derived fields/provenance and known split factors where applicable.
  3. Define per-provider/feed basis matrix and canonical field(s) for downstream total-return/feature use.
  4. Feed decisions into `dividend-batch-key-contract-draft.md` and M2 P0/P1 specs (`RM-03/04`).
- **Acceptance/evidence:** provider/feed basis matrix, canonicalization rule proposal, and list of affected consumers/tests.

## UNK-003 — Survivorship magnitude (`FR-UNI-01`, `RK-01`, blocked by RM-01)

- **Known proxy:** 1,708 inactive securities (0 `delisted_date`), 1,332 score rows/29 currently-inactive securities, 1,507,383 feature rows for inactive securities; cannot measure true survivor-vs-PIT delta yet.
- **Validation steps (post-RM-01 design/data readiness):**
  1. Define PIT membership reconstruction method (delisted/listing metadata or historical membership evidence).
  2. Compute/read-only compare eligible universe counts and performance/ranking metrics on survivor-only vs PIT-aware membership for agreed periods.
  3. Quantify delta and document materiality against decision thresholds.
- **Acceptance/evidence:** reproducible comparison note/report with method, period, universe definitions, and delta metrics.

## UNK-004 — Reports Center as-of/fetch-time (`BI-37`, `FR-REP-02`, `RK-09`)

- **Known:** deterministic on-demand markdown from loaded context (`app/views/dashboard.py`), latest-path labeling/filename; no inspected persistence, stored `resolved_as_of`/`fetch_time`, or historical as-of selection.
- **Validation steps:**
  1. Review/approve `reports-center-asof-contract-draft.md` with stakeholders.
  2. In a running non-prod/read-only environment, confirm UI behavior: visible as-of/fetch-time, selected context date, download naming/content metadata, and absence/presence of historical selection.
  3. Capture screenshots/logs/notes as evidence (no code changes in this stage).
  4. Convert gaps into approved M2 acceptance criteria (`TSK-011/024`).
- **Acceptance/evidence:** runtime observation note + approved contract + test/AC list.

## UNK-005 — Dividend batch duplicate-key behavior (`DA-21`, `FR-DIV-01`, `RK-10`)

- **Known:** PK `(security_id, ex_dividend_date, provider)` omits `feed`; unconditional upsert overwrites; no in-batch dedupe in loader; no stored OPENBB same-key duplicates observed.
- **Validation steps (safe, controlled only):**
  1. Review/approve `dividend-batch-key-contract-draft.md` including key/feed-evidence and date-preservation semantics.
  2. In an **isolated disposable database or explicit transaction-rollback sandbox**, construct a minimal duplicate-key batch case and observe behavior of current upsert pattern (or document expected PostgreSQL constraint behavior from controlled test harness).
  3. Specify deterministic pre-deduplication precedence and tests (`V-DIV-01..05`).
  4. **Do not** run against shared/production DB; no persistent writes.
- **Acceptance/evidence:** isolated test/design note with observed/expected behavior, chosen contract, and verification cases.

## UNK-006 — Migration numbering gap (resolved)

- **Known:** 104 files (`V0002..V0106`, missing `V0045`) reconcile with 105 ledger rows (baseline V0001..V0106, missing 45).
- **Optional step:** document historical rationale for V0045 gap if discoverable from governance records; otherwise record as undocumented non-blocking gap.
- **Acceptance/evidence:** optional governance note; tracker remains Resolved.

## UNK-007 — External systems inventory (`RK-13`, reproducibility/recovery scope)

- **Known:** no in-repo/DB evidence of external scheduler, object store, backup/restore, or provider audit-log state.
- **Validation steps:**
  1. Complete `external-systems-inventory-template.md` with platform/SRE, data governance, and provider owners.
  2. Collect evidence references for scheduling, artifact retention, DB backup/restore tests, and provider audit/terms controls.
  3. Link gaps to `DEC-001/008`, `RM-04/05`, and M3/M4 planning.
- **Acceptance/evidence:** completed inventory with owners, controls/retention, recovery evidence, and explicit unknowns.

## Execution guardrails
- No source/test/config modifications in recovery preparation.
- No writes to shared databases; any DB-touching validation for UNK-005 must be isolated and non-persistent.
- Record all outcomes in `decision-unknown-tracker.md` validation log with evidence paths.

## Availability / conservative proxy policy (US1, 2026-11-18)

For covered replay paths, a fact with unknown `available_at` or known-at timing is excluded or explicitly labeled as a conservative proxy. A proxy becomes approved only when all four items are recorded before it is used as acceptance evidence: data basis, approval owner, decision reference, and expiry/review date. An unrecorded proxy is not evidence of availability.

This policy applies to RM-02 timing backfill, RM-03 dividend evidence, UNK-001 close basis, UNK-002 dividend amount basis, and UNK-003 survivor-vs-PIT comparison. It does not authorize consumer cutover or promotion claims.
