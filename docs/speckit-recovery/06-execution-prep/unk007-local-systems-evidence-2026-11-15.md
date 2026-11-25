# UNK-007 Local/Repo Systems Evidence (2026-11-15)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | Read-only inspection of repo config and running local containers; no external system access |
| Status | **Local/dev evidence gathered; prod/external evidence pending** |
| Related | `UNK-007`, `RK-13`, `NFR-REPRO-04` (scope-limited), `DEC-001/008`, `external-systems-inventory-template.md` |

## Local runtime evidence (observed)
- Running containers (Docker): `dividend_equity_crispdm-postgres-1` (`postgres:17.11`), `dividend_equity_crispdm-api-1`, `dividend_equity_crispdm-worker-1`, `dividend_equity_crispdm-streamlit-1`.
- Streamlit health endpoint reachable: `http://127.0.0.1:8501/_stcore/health` returned `ok`.
- Ports (compose intent/observed): Streamlit `127.0.0.1:8501->8501`, Postgres bound to loopback per compose (`127.0.0.1:5432:5432`).

## Repo-config evidence (redacted/structural)
- `docker-compose.yml`: defines `postgres` (pinned image+digest, tuned settings, `pgdata` volume, schema init mount), `migrate`, `streamlit`, `api`, `worker`; API/Streamlit bound to `127.0.0.1`; `API_KEY` required for API startup; `OPS_ADMIN_TOKEN` gates operator controls; worker runs `scripts.ops_worker` (catalog-limited tasks), nightly ETL noted as host systemd timer (not composed schedule).
- `ops/systemd/`: `dividend-etl.service`, `dividend-etl.timer`, `install.sh`, `wait_for_db.py` present (host-scheduled ETL path referenced).
- `.env.example` keys (names only, values redacted): `DATABASE_URL`, `SEC_USER_AGENT`, `OPENBB_PROVIDER`, `MIN_RECALL`, `POSTGRES_PASSWORD`, `API_KEY`, `OPS_ADMIN_TOKEN`, `API_BASE_URL`, `API_RATE_LIMIT_PER_MINUTE`, `API_ENABLE_DOCS`, `ENFORCE_DIVIDEND_RECENCY`.
- `Dockerfile`: Python 3.12 slim, non-root `app` user, OpenBB prebuilt/static reference handling, `OPENBB_AUTO_BUILD=false`.

## Gaps remaining (external/operational, not in repo)
- Actual scheduler/orchestrator state and run history in target environments (beyond local compose/systemd files).
- Object/artifact store location, retention, access controls, and durability evidence for run manifests/reports/artifacts.
- Database backup schedule, storage, and **tested restore** evidence.
- Secret management/injection in deployed environments and rotation/audit posture.
- Provider portal ToS/redistribution terms and request/audit-log retention (`DEC-001` linkage).
- CI/CD enforcement of locks/reproducibility controls (`DEC-008` linkage).

## Recommended completion
- Populate `external-systems-inventory-template.md` with owner-attested entries and evidence links for each environment; record Unknown/N-A explicitly where applicable.
