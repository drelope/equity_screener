# External Systems Inventory Template (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Status | **Draft template; completion pending owner input** |
| Purpose | Capture out-of-repo operational dependencies and controls not evidenced in repository/DB inspection |
| Traceability | `UNK-007`, `NFR-REPRO-04` (scope-limited), `NFR-GOV-03`, `RK-13`, `TSK-004` |

> **Instructions:** Complete with factual, evidence-backed entries. Record access control and retention at metadata level; do not paste secrets, tokens, or sensitive payloads. Mark unknowns explicitly.

## 1. Inventory

| ID | System / service | Category | Purpose in workflow | Owner/team | Environment(s) | Access/control model | Retention / backup | Recovery/restore evidence | Audit/log availability | Related decisions/unknowns | Status | Evidence link/ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXT-001 |  | scheduler/orchestrator |  |  | dev/stage/prod |  |  |  |  | UNK-007 | Unknown |  |
| EXT-002 |  | object/artifact store |  |  |  |  |  |  |  | UNK-007, RM-04/05 | Unknown |  |
| EXT-003 |  | database backup/restore |  |  |  |  |  |  |  | UNK-007, NFR-REPRO-04 | Unknown |  |
| EXT-004 |  | secret manager / env injection |  |  |  |  |  |  |  | TSK-005, NFR-SEC-03 | Unknown |  |
| EXT-005 |  | CI/CD runner |  |  |  |  |  |  |  | DEC-008, NFR-REPRO-01/02 | Unknown |  |
| EXT-006 |  | provider portal/audit logs (yfinance/FMP/SEC/OpenBB) |  |  |  |  |  |  |  | DEC-001, NFR-GOV-03 | Unknown |  |
| EXT-007 |  | monitoring/alerting |  |  |  |  |  |  |  | NFR-OBS-* | Unknown |  |

## 2. Recovery and reproducibility notes

| Topic | Current state (evidence) | Gap/risk | Required action | Owner | Due | Status |
|---|---|---|---|---|---|---|
| DB backup frequency & tested restore |  |  |  |  |  | Pending |
| Run artifact/manifests storage durability |  |  |  |  |  | Pending |
| Scheduler run history / replayability |  |  |  |  |  | Pending |
| Provider request/audit trace retention |  |  |  |  |  | Pending |

## 3. Completion criteria
- [ ] All production-relevant external dependencies for ingestion, scoring, reporting, and storage are listed or explicitly marked N/A with rationale.
- [ ] Each entry has owner, environment, control/retention summary, and evidence reference (or Unknown).
- [ ] Gaps affecting `DEC-001/008`, `RM-04/05`, or reproducibility/recovery are linked to tracker items and owners.
