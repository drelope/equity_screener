# Deployment Runbook — Dividend Equity Screener

Local-first MVP. This runbook covers the release procedure, rollback, secret
handling, and the nightly schedule. Cloud (Azure) is deliberately deferred
until the local MVP is reproducible and walk-forward evaluation is passing.

## 1. Environment layout

| Component | Where | Config |
|---|---|---|
| PostgreSQL 17.11 | Docker Compose service `postgres` (image pinned by digest) | `docker-compose.yml` |
| Migrations | Compose service `migrate` / `python -m scripts.migrate` | `sql/migrations/` + `scripts/init_db.py` |
| ETL | `python -m scripts.run_full_etl` (stages 0-9; stage 10 labels opt-in) | `.env` |
| API | Compose service `api` / `uvicorn api.main:app --port 8000` | `API_KEY` (required by every Compose command), `DATABASE_URL`; optional `API_RATE_LIMIT_PER_MINUTE` (default 120), `API_ENABLE_DOCS` (docs off unless set) |
| UI | Compose service `streamlit` (`127.0.0.1:8501`) | `DATABASE_URL`, `OPS_ADMIN_TOKEN` |
| Task worker | Compose service `worker` (`scripts.ops_worker`) | `DATABASE_URL`, `SEC_USER_AGENT` |

All published ports (5432, 8000, 8501) are bound to `127.0.0.1`. Compose reads
`POSTGRES_PASSWORD` (default `dividend`), `API_KEY`, `OPS_ADMIN_TOKEN` and
`SEC_USER_AGENT` from the environment or `.env`; see `.env.example`.

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
   docker compose up -d api streamlit worker
   ```

   `API_KEY` must be exported in the shell for every `docker compose`
   command, including these, because the `api` service declares it required.
   Load it from `.env` first (`export API_KEY="$(grep '^API_KEY=' .env | cut -d= -f2-)"`);
   the full steps, including PowerShell, are in the README's
   "Start PostgreSQL with Docker Compose" section.

4. Sanity check:

   ```bash
   curl -s localhost:8000/health
   curl -s -H "X-API-Key: $API_KEY" localhost:8000/metrics/enriched/AAPL
   ```

   The API imports OpenBB at startup. If it is crash-looping with
   `PermissionError: .../openbb/.build.lock`, the image was built before the
   OpenBB build moved into the Dockerfile — rebuild it (§2.4a).

5. Run the nightly ETL (see §5 for automation). Stage 3 keeps the 12-month
   dividend lookback (`DIVIDEND_LOOKBACK_START`, default 2025-01-01) and
   accrues forward; **after the PoC gate passes**, switch the ETL/scheduler to
   total history once with `--dividend-full-history`
   (see [data-acquisition.md](data-acquisition.md)).

### 2a. Rebuilding the image

The Compose services build from the `Dockerfile` in this repository, so a
code change needs a rebuild before the running container sees it:

```bash
docker compose build
docker compose up -d
```

A running container keeps the image it was started from: editing a file in
the repository does not change what `/app` contains. Check with
`docker compose exec api ls /app/app`, not with `ls app`.

Two things the image build does that a plain `pip install` does not:

- **OpenBB's static package is built during the build, as root.** The
  published wheels carry no `assets/reference.json`, so a fresh install
  rebuilds the package on its first import, into `site-packages`. At runtime
  that import runs as the unprivileged `app` user against a root-owned
  directory, and it dies with `PermissionError: .../openbb/.build.lock`. The
  Dockerfile builds it instead, where the directory is still writable, and
  fails the build if the reference file did not land. `OPENBB_AUTO_BUILD=false`
  then stops the runtime from trying again.
- **OpenBB's platform directory is writable where it has to be.** OpenBB
  creates `~/.openbb_platform` and writes its settings there on import. The
  `api` service runs on a read-only rootfs, so it gets that one directory as
  a tmpfs (`mode=1777`); the other services have a writable rootfs and need
  nothing.

`ObbCredentials.json` is deliberately **not** in the image: `.dockerignore`
excludes it and Compose bind-mounts it read-only at `/app/ObbCredentials.json`
for the `api`, `streamlit` and `worker` services. The file must exist on the
host before `docker compose up`, or Docker creates a directory in its place
and the provider keys are silently absent.

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
docker compose up -d api streamlit worker
```

**Nightly health check:** after any deploy (and every morning), confirm the
03:00 ET run and the data modules with `python -m scripts.verify_nightly_run`
— full single-owner process in
[docs/nightly-verification.md](nightly-verification.md).

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

Problem: `scripts.run_full_etl` is not scheduled by `docker-compose.yml`. The
Compose `worker` only runs tasks and schedules queued from the web app's
Operations page; the nightly ETL stays on the host. Two supported paths:

### Option A — Airflow (recommended if Airflow already in the stack)

A ready DAG is provided at `airflow/dags/dividend_etl_dag.py` (daily 03:00 ET,
local Python script). Deploy Airflow with that DAG mounted, set the repo path
inside the DAG, and let it own retries/failure emails.

### Option B — systemd timer (zero extra dependencies, local-first)

Templates live at `ops/systemd/dividend-etl.service` and
`ops/systemd/dividend-etl.timer` (daily 03:00 ET, DST-aware). The paths in them
already match this host's checkout, so no editing is needed here:

```bash
sudo cp ops/systemd/dividend-etl.service ops/systemd/dividend-etl.timer /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/dividend-etl.{service,timer}
sudo systemctl daemon-reload
sudo systemctl enable --now dividend-etl.timer
systemctl list-timers dividend-etl.timer    # confirm a NEXT time
```

The unit runs as `User=drelo` (not root) and applies systemd hardening: a
read-only system hierarchy except the checkout, a private `/tmp`, dropped
namespaces, and a restricted address-family set. Two consequences:

- **Protect the `.env`.** It holds `POSTGRES_PASSWORD`, `API_KEY` and
  `SEC_USER_AGENT`, and the unit reads it as the service user. Tighten it once:
  `chmod 600 .env`. The file is gitignored; never commit it.
- **If the checkout is on a WSL2 `/mnt/<drive>` 9p mount, file modes are
  cosmetic.** That mount reports every file as `0777` and ignores `chmod`, so
  `sudo systemctl` may warn the unit files are executable/world-writable. The
  warning is harmless for a local checkout, but a real host should carry the
  `chmod 644` above and a metadata-enabled mount (or a native filesystem).

Four things in the unit that are not obvious, each of which silently breaks a
nightly rather than failing loudly:

- **`TimeoutStartSec=12h` is mandatory.** The systemd default for a `oneshot`
  is `DefaultTimeoutStartSec=90s`. Without it the ETL is killed 90 seconds in,
  every night, and records a failed run that looks like a legitimate scheduled
  attempt. `systemctl show -p DefaultTimeoutStartUSec` returns `1min 30s` on
  Ubuntu 22.04.
- **`ExecStartPre` waits for the database.** The warehouse is a Docker container,
  and `After=docker.service` only *orders* the two units — it does not make
  docker ready, nor does it make the container up. `ops/systemd/wait_for_db.py`
  blocks until a real query succeeds (600s budget) so a boot race is not recorded
  as a pipeline fault. `Wants=`, not `Requires=`, so a docker restart cannot tear
  down an ETL that is already mid-write.
- **Journal output.** `StandardOutput=journal` with
  `SyslogIdentifier=dividend-etl`; read it with
  `journalctl -u dividend-etl -f`.
- **Runs unprivileged.** `User=drelo` plus `NoNewPrivileges`, `ProtectSystem=strict`
  and the rest of the hardening block. The only writable path is the checkout
  (`ReadWritePaths`), which the ETL needs for `data/` archives. If the checkout
  moves, update `WorkingDirectory`, `EnvironmentFile`, `ExecStartPre`,
  `ExecStart` and `ReadWritePaths` together — a stale `ReadWritePaths` turns a
  data/ write into a failed nightly.

**WSL2 caveat (this host).** The timer only fires while the WSL2 VM is running.
A laptop that is asleep or shut down at 03:00 does not run the ETL then;
`Persistent=true` catches it up on the next WSL start instead. The freshness
SLA is therefore bounded by when this machine is awake, not by the clock — do
not read a green freshness check on a host that sleeps. For a schedule that must
hold regardless, use a real host (Option C) rather than relying on `Persistent`.

The VM's own memory comes from `C:\Users\<you>\.wslconfig` (currently
`memory=24GB`, `swap=8GB`). Changing it requires `wsl --shutdown`, which stops
Docker and any ETL mid-run — do it deliberately, never at 03:00.

At Azure time this same job becomes an Azure Functions / Container Apps Job
(`azure/README.md`), so the entrypoint stays `python -m scripts.run_full_etl`
in all three options.

## 6. Secret and key handling

- **`API_KEY`**: single shared key today. Rotate it in exactly two places —
  the `API_KEY` export/shell or Compose `environment`, and any consumer
  (`X-API-Key`). Unset/blank keys make the API return 503 rather than open up.
- **`DATABASE_URL`**: local dev user `dividend:dividend` is intentionally
  weak for the loopback-only container (Compose publishes 5432 on `127.0.0.1`);
  set `POSTGRES_PASSWORD` and do **not** reuse the default for any networked
  deployment.
- **`OPS_ADMIN_TOKEN`**: gates the web app's operator controls (12+ characters;
  empty = read-only). There is no default token.
- **`SEC_USER_AGENT`**: must be a real contact string. Enforced before any SEC
  request (`src/crispdm/sec_client.py`); the placeholder
  `Your Name your.email@example.com` fails fast.
- **`ObbCredentials.json`**: the OpenBB provider keys, read at runtime from a
  read-only bind mount. `.dockerignore` keeps the file out of the image and
  `.gitignore` keeps it out of source control, so it never sits in a layer
  that outlives the container. It must exist on the host before
  `docker compose up`, or Docker mounts a directory in its place and the
  provider calls fail with missing credentials rather than with a clear
  error. Rotate by replacing the file on the host and restarting the
  services.
- **At Azure migration:** move `API_KEY`, `DATABASE_URL`, OpenBB keys, and the
  SEC agent into Azure Key Vault and load them as App/Container App settings;
  nothing goes into source control or image layers. `.env` remains local-only
  and is gitignored.

## 7. Monitoring (as-is and target)

- As-is: no `pg_stat_statements` dashboards wired; Compose enables the
  extension and `log_lock_waits`, and `/health` plus container `healthcheck`
  give the API/DB liveness. `postgres` is capped at `mem_limit: 10g`.
- Target at Azure: Application Insights for the API and Function/Job runs;
  log-instrument `run_full_etl` per-stage exit codes (already printed) into
  Insights; alert on non-zero stage exits.