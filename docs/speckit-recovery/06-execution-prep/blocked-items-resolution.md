# Blocked Items Resolution (2026-11-15)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Purpose | Address each remaining blocker with completed in-scope actions, residual constraints, and exact unblock steps |
| Constraints | No source/test/config changes; no shared-DB writes; no pipeline/test execution; approvals/policy decisions not fabricated |

## Summary

| Blocker | Status now | Addressed in-scope | Remaining to unblock |
|---|---|---|---|
| M1 approvals (`EX-001..05`, `DEC-001..08`) | **Blocked (human/governance)** | Checklists/templates prepared: `m1-readiness-checklist.md`, `m1-decision-log-template.md`, `constitution-disposition-and-exceptions.md`, `decision-unknown-tracker.md` | Stakeholder review session, named authority, recorded dispositions/owners/dates/evidence |
| UNK-004 Reports Center as-of/fetch-time | **Partially addressed** | Code evidence + `reports-center-asof-contract-draft.md`; runtime service confirmed reachable (`dividend_equity_crispdm-streamlit-1`, `127.0.0.1:8501`, `/_stcore/health` ok) | Interactive/browser confirmation of displayed `resolved_as_of`/fetch time, historical selection, download metadata/content in running UI |
| UNK-005 dividend batch duplicate-key/date overwrite | **Partially addressed** | Contract draft + isolated synthetic and actual-`DIVIDEND_UPSERT` disposable-DB tests (`postgres:17-alpine`, created/destroyed) in `unk005-isolated-batch-test-2026-11-15.md` and `unk005-actual-upsert-isolated-test-2026-11-15.md` (CardinalityViolation, NULL overwrite, feed collision at PK, deterministic pre-dedupe) | Approve precedence/date-preservation/feed-evidence contract; validate actual loader runtime/batch execution in isolated project test DB (no shared writes) |
| UNK-001/002 adjustment/basis | **Partially addressed** | Read-only DB/repo analysis in `unk001-unk002-basis-analysis-2026-11-15.md` and `repo-validations-2026-11-15.md` (adjusted_close NULL, split samples, provider/feed dividend matrix, cross-provider diffs) | Approved canonical basis decisions (`FR-ADJ-01`, `FR-DIV-08`), broader sample/provider confirmation, contract/spec updates |
| UNK-007 external systems | **Partially addressed (local)** | `external-systems-inventory-template.md` + `unk007-local-systems-evidence-2026-11-15.md`: local compose containers (`postgres:17.11`, api, worker, streamlit), ports/volumes/health, systemd ETL artifacts, and redacted env-key inventory observed | Owner-confirmed prod/external evidence for scheduler/run history, object/artifact store, backup+tested restore, secret mgmt, provider audit/terms across environments |
| UNK-003 survivorship/PIT delta | **Blocked (depends on RM-01)** | Proxy evidence documented (inactive securities/scores/features; no `delisted_date`) | PIT membership reconstruction/design (RM-01), then reproducible survivor-vs-PIT comparison |
| Phase 4 M2 conversion | **Blocked (gate)** | P0 drafts ready (`m2-specify-p0.md`, `m2-plan-p0.md`, `m2-tasks-p0.md`) | M1/Phase 2 approvals, then convert to traced execution artifacts with `AC-P0-*`/RTM gates |

## Detailed unblock actions

### 1) M1 approvals and decisions (human)
- **Action:** Run Phase 1 using `execution-sequence.md`; capture outcomes in `m1-decision-log-template.md`.
- **Minimum outputs:** constitution disposition authority/date, `EX-001..05` resolved or time-bounded with controls/expiry, owners/dates for `DEC-001..08` and `UNK-001..07`, go/no-go for M2 conversion.
- **Priority decisions for M2:** `DEC-002` (holdout), `DEC-003` (acceptance-policy versioning), `DEC-004` (cost/exposure-matched benchmark), `DEC-008` (lock strategy).

### 2) UNK-004 (interactive runtime confirmation)
- **Completed:** repo shows deterministic in-memory report generation and latest-date labeling/filename in `app/views/dashboard.py`; Streamlit service health endpoint reachable.
- **Needed:** in running UI, verify Reports Center displays or omits `resolved_as_of`/`fetch_time`/generation metadata, supports/denies historical as-of selection, and download naming/contents; capture screenshot/note.
- **Fallback if UI access unavailable:** approve contract draft as target state and add acceptance tests in implementation phase.

### 3) UNK-005 (project-path validation)
- **Completed (safe):** isolated synthetic and actual-`DIVIDEND_UPSERT` tests confirm multi-values same-key CardinalityViolation, unconditional NULL overwrite of dates, provider-scoped PK feed collision/supersession, and deterministic pre-dedupe viability.
- **Needed:** approved contract (conflict key/feed evidence retention, pre-dedupe precedence, `COALESCE`/correction rules), then validate actual loader batching/runtime path in isolated project test DB/schema with rollback/teardown.
- **Do not:** run against shared `dividend` DB.

### 4) UNK-001/002 (canonical basis)
- **Completed:** read-only evidence matrices/samples captured.
- **Needed:** stakeholder/quant/data decision on canonical stored/derived bases, provider-term/documentation review as applicable (`DEC-001`), and M2 spec updates (`TSK-019/021`).

### 5) UNK-007 (external evidence)
- **Completed:** template and local/dev+repo-config observations recorded (`unk007-local-systems-evidence-2026-11-15.md`).
- **Needed:** platform/SRE/governance-completed inventory with evidence refs for prod/non-prod scheduler, artifact/object storage, DB backup and tested restore, secret management, CI/CD, and provider portal/audit-log retention.

### 6) UNK-003 (post-RM-01)
- **Needed:** implement/specify PIT membership reconstruction inputs, then run read-only or isolated comparison and record delta/materiality.

## Execution readiness statement
- **Ready now (after approvals):** convert P0 M2 drafts, finalize contracts/inventories, and run remaining controlled validations per `validation-plans-unk001-007.md`.
- **Not claimable now:** implementation complete, verification passed, promotion-grade/readiness beyond documented baseline, or resolution of human/external blocked items.
