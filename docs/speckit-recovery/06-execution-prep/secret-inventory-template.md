# Secret and Credential Inventory Template (Draft)

| Field | Value |
|---|---|
| Stage | 6 — Execution preparation |
| Date | 2026-11-15 |
| Purpose | Support secret inventory/rotation policy for `NFR-SEC-03`, `PE-28`, `TSK-005` (governance artifact only) |
| Status | **Template; requires owner completion. Do not record secret values in this document.** |

## Instructions
- Record secret **metadata only** (name, purpose, system, owner, storage location type, rotation). **Never** paste keys, passwords, tokens, or connection strings.
- Identify where each secret is used (local dev, CI, containers, production-like env) and how access is controlled.
- Define rotation cadence, last rotation evidence, break-glass/revocation procedure, and detection/response contacts.
- Preserve existing controls: `.gitignore` patterns, gitleaks CI, non-root containers, least-privilege access (`PE-26/27/28`).

## Inventory
| Secret ID | Name/type | Purpose | Systems/components using it | Storage location (type/ref) | Provisioning method | Access scope/owners | Rotation cadence | Last rotated (date/evidence) | Revocation procedure | Detection/alerting | Status | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SEC-001 | `POSTGRES_PASSWORD` / DB credentials | Warehouse authentication | Postgres, migrate, ETL, API, Streamlit, ops (as configured) | `.env`/compose env/secret manager (specify) |  |  |  |  |  |  | Pending | Confirm non-default credentials in shared environments |
| SEC-002 | `API_KEY` | FastAPI data-route authentication | `api/main.py`, clients/Streamlit integrations | Env/secret store (specify) |  |  |  |  |  |  | Pending | Rate limits/auth already present; rotation policy needed |
| SEC-003 | `OPS_ADMIN_TOKEN` | Ops control authorization | Streamlit/ops control plane | Env/secret store (specify) |  |  |  |  |  |  | Pending | Empty/min-length disables controls by design |
| SEC-004 | Provider API keys (FMP, Polygon, etc.) | External data access | `ObbCredentials.json`/OpenBB/provider clients | Local credentials file/secret store (specify) |  |  |  |  |  |  | Pending | File git-ignored; document per-provider ownership |
| SEC-005 | `SEC_USER_AGENT` contact string | SEC fair-access identification | SEC clients/loaders | `.env`/config |  |  |  |  |  |  | Pending | Not a secret but required governed config |
| SEC-006 | `llm_api_key` (if used) | Local/remote LLM endpoint auth | `app/llm_client.py` (optional) | Env/secret store (specify) |  |  |  |  |  |  | Pending | LLM disabled by default/loopback-first |
| SEC-007 | Other (specify) |  |  |  |  |  |  |  |  |  | Pending |  |

## Rotation and incident policy (to complete)
| Item | Current state | Target policy | Owner | Target date | Evidence | Status |
|---|---|---|---|---|---|---|
| Rotation schedule by secret class | Unknown | Define |  |  |  | Pending |
| Emergency revocation/runbook | Unknown | Define |  |  |  | Pending |
| CI/secret scanning response | gitleaks present (descriptive control) | Define triage/remediation SLA |  |  |  | Pending |
| Least-privilege review | Partial controls present | Periodic review process |  |  |  | Pending |
| Secret storage standard (dev/CI/prod) | Unknown | Define approved stores and prohibited patterns |  |  |  | Pending |
