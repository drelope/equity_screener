# Deployment Runbook — Dividend Equity Screener

Local-first MVP. This runbook covers the release procedure, rollback, secret
handling, and the nightly schedule. Cloud (Azure) is deliberately deferred
until the local MVP is reproducible and walk-forward evaluation is passing.

## 1. Environment layout

| Component | Where | Config |
|---|---|---|
| PostgreSQL 17.11 | Docker Compose service `postgres` (image pinned by digest) | `docker-compose.yml` |
| Migrations | Compose service `migrate` / `python -m scripts.migrate` | `sql/migrations/` + `scripts/init_db.py` |
| ETL | `python -m scripts.run_full_etl` (stages 0-6) | `.env` |
| API | Compose service `api` / `uvicorn api.main:app --port 8000` | `API_KEY`, `DATABASE_URL` |
| UI | Compose service `streamlit` (port 8501) | `DATABASE_URL` |

Volumes: `pgdata` persists all data; schema is mounted from `sql/schema.sql`
for first initialization only.

## 2. Release procedure

1. From a branch (see `CONTRIBUTING.md`), land a PR that is CI-green and
   passes the walk-forward gate (`python -m scripts.evaluate_walk_forward`).
2. Tag the release after merge:

   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

3. Deploy to local:

   ```bash
   docker compose pull        # immutable, digest-pinned images
   docker compose up -d postgres
   docker compose up migrate  # apply pending sql/migrations/*
   docker compose up -d api streamlit
   ```

4. Sanity check:

   ```bash
   curl -s localhost:8000/health
   curl -s -H "X-API-Key: $API_KEY" localhost:8000/metrics/enriched/AAPL
   ```

5. Run the nightly ETL (see §5 for automation). Stage 2 keeps the 12-month
   dividend lookback (`DIVIDEND_LOOKBACK_START`, default 2025-01-01) and
   accrues forward; **after the PoC gate passes**, switch the ETL/scheduler to
   total history once with `--dividend-full-history`
   (see [data-acquisition.md](data-acquisition.md)).

## 3. Database backups

Before any risky operation (schema migration, debug sweep), snapshot the data:

```bash
docker compose exec -T postgres pg_dump --username=dividend --dbname=dividend \
  --format=custom --file=/var/lib/postgresql/data/backup_$(date +%Y%m%d).dump
```

## 4. Rollback procedure

Rollback = revert to the previous release tag, in the reverse order of deploy:

```bash
git checkout v0.2.0            # previous known-good tag
docker compose up -d postgres  # data volume is unchanged
docker compose up migrate      # migrations are forward-only: see note below
docker compose up -d api streamlit
```

**Migration note:** `sql/migrations/*` are forward-only (Flyway-style). If a
failed migration is already applied, do **not** re-run it against the same
database — `V*`-tracked files are recorded in the schema-migration tracking
table (`scripts/migrate.py`). Fix forward: apply a new corrective migration, or
restore `pgdata` from the §3 dump and then re-run `migrate` to the target
version. Only rebuild the volume as a last resort:

```bash
docker compose down -v              # DESTROYS the postgres volume
docker compose up -d postgres       # re-runs sql/schema.sql from scratch
```

Image-level rollback uses the digest-pinned tags: point `image:` back at the
previous `@sha256:` digest and `docker compose up -d`. This is why the digest is
pinned — a tag (`postgres:17.11`) can be repointed upstream; a digest cannot.

## 5. Nightly schedule

Problem: `scripts.run_full_etl` is currently invoked manually
(`docker-compose.yml` has no scheduler). Two supported paths:

### Option A — Airflow (recommended if Airflow already in the stack)

A ready DAG is provided at `airflow/dags/dividend_etl_dag.py` (daily 03:00 ET,
local Python script). Deploy Airflow with that DAG mounted, set the repo path
inside the DAG, and let it own retries/failure emails.

### Option B — systemd timer (zero extra dependencies, local-first)

Ready-to-edit templates live at `ops/systemd/dividend-etl.service` and
`ops/systemd/dividend-etl.timer` (daily 03:00 ET). Copy them to
`/etc/systemd/system/`, fix `WorkingDirectory` / `ExecStart` /
`EnvironmentFile` for your host, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dividend-etl.timer
```

At Azure time this same job becomes an Azure Functions / Container Apps Job
(`azure/README.md`), so the entrypoint stays `python -m scripts.run_full_etl`
in all three options.

## 6. Secret and key handling

- **`API_KEY`**: single shared key today. Rotate it in exactly two places —
  the `API_KEY` export/shell or Compose `environment`, and any consumer
  (`X-API-Key`). Unset/blank keys make the API return 503 rather than open up.
- **`DATABASE_URL`**: local dev user `dividend:dividend` is intentionally
  weak for the localhost container; do **not** reuse it for any networked
  deployment.
- **`SEC_USER_AGENT`**: must be a real contact string. Enforced before any SEC
  request (`src/crispdm/sec_client.py`); the placeholder
  `Your Name your.email@example.com` fails fast.
- **At Azure migration:** move `API_KEY`, `DATABASE_URL`, OpenBB keys, and the
  SEC agent into Azure Key Vault and load them as App/Container App settings;
  nothing goes into source control or image layers. `.env` remains local-only
  and is gitignored.

## 7. Monitoring (as-is and target)

- As-is: no `pg_stat_statements` dashboards wired; Compose enables the
  extension, and `/health` plus container `healthcheck` give the API/DB liveness.
- Target at Azure: Application Insights for the API and Function/Job runs;
  log-instrument `run_full_etl` per-stage exit codes (already printed) into
  Insights; alert on non-zero stage exits.