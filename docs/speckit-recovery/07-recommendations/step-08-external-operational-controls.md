# Step 8 — External/Operational Controls (Prepared)

| Field | Value |
|---|---|
| Recommendation | Resolve provider/secret/schema/boundary decisions and collect external operational evidence |
| Status | **Prepared; external/human evidence and decisions pending** |
| Traceability | `DEC-001/006/007/008`, `UNK-007`, `NFR-GOV-03`, `NFR-SEC-03`, `NFR-REPRO-01/02/04`, `RK-13`, `RK-15`, `TSK-004/005/006/007/026/027` |

## 1. Executed preparation (done)
- [x] Drafted provider terms and secret inventory templates (metadata-only): `../06-execution-prep/provider-terms-inventory-template.md`, `../06-execution-prep/secret-inventory-template.md`.
- [x] Drafted external systems inventory template: `../06-execution-prep/external-systems-inventory-template.md`.
- [x] Gathered local/dev evidence: `../06-execution-prep/unk007-local-systems-evidence-2026-11-15.md` (compose containers/services, ports/health, `ops/systemd` artifacts, redacted env key names; no external/prod access).
- [x] Consolidated request package/templates: `../06-execution-prep/human-external-action-package.md`.

## 2. Decisions required (human)

| Decision | Recommended direction (draft) | Evidence/action |
|---|---|---|
| `DEC-001` Provider terms/licensing | Record per-provider ToS/redistribution/cache/derived-data posture; mark Unknown explicitly; restrict use where rights unclear | Complete provider terms inventory with legal/governance review |
| `DEC-006` Streamlit DB boundary | Document explicit exception with least-privilege/read-only controls **or** route reads through API/service boundary | Architecture/security review; record allowed reads/credentials/compensating controls |
| `DEC-007` Schema canonicalization | Declare canonical runtime schema (e.g. `sql/schema.sql` + ordered migrations/ledger) and archive or clearly document non-runtime `sql/silver_schema.sql` | Reconcile runtime references; migration/ledger governance |
| `DEC-008` Lock strategy | Enforce pinned/hashed dependency lock consistently in local, CI, Docker | DevOps/platform decision and pipeline/image enforcement (Step 6 linkage) |

## 3. External evidence requests (`UNK-007` / operations)

| Area | Minimum evidence to collect | Suggested owner |
|---|---|---|
| Scheduler/orchestrator | Prod/non-prod schedules, run history, retries/alerts, access controls (beyond local compose/systemd files) | Platform/SRE |
| Object/artifact store | Manifest/report/artifact storage location, retention, immutability/versioning, encryption, access | Platform/Data Eng |
| DB backup/restore | Backup frequency/retention/encryption and **last tested restore** result (RPO/RTO) | DBA/Platform |
| Secret management | Injection/rotation mechanism and audit trail (no secret values) | Security/Platform |
| CI/CD & reproducibility | Lock enforcement, build provenance, environment parity evidence | DevOps |
| Provider audit/terms | Request/audit log availability and terms evidence per provider | Data Governance/Legal |

## 4. Completion criteria
- All relevant environments inventoried in external systems template or explicitly N/A/Unknown with owner and follow-up date.
- `DEC-001/006/007/008` recorded in decision log with evidence.
- No secret values stored in repo artifacts; sensitive evidence referenced securely.
