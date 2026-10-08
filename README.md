# Dividend Equity CRISP-DM Implementation

A local-first nightly dividend-equity CRISP-DM end-to-end data engineering pipeline and high-performance API for Python. Using Dockerized PostgreSQL, the API designed to ingest, normalize, and serve SEC EDGAR/XBRL financial data, and supplemented with real-time financial ratios and valuation metrics from OpenBB reproducible dividend screening and ranking workflow.

This platform automatically syncs official SEC company metadata, securely
downloads raw inline XBRL (iXBRL) preferred-stock filings into a PostgreSQL
database, and transforms the complex financial tags into normalized facts and
time-series data for a wide range of financial metrics. The data is modeled and
served through a secure FastAPI backend. Real-time financial ratios, valuation
multiples, analyst consensus, and company profiles are seamlessly integrated
from OpenBB to provide comprehensive data-driven investment analytics.

Stack:
- Python 3.10-3.14
- PostgreSQL
- OpenBB
- SEC EDGAR/XBRL
- pandas/numpy/scikit-learn
- Streamlit
- Docker Compose

System Architecture:
- Data Collection: SEC EDGAR API (filings, facts) + OpenBB (ratios, fundamentals, valuations)
- Orchestration: scripts.run_full_etl (stages 0-9, plus optional labels as stage 10); the nightly run is started by a host systemd timer, Apache Airflow optional
- Data Lake (raw): PostgreSQL (Dockerized, localhost)
- Data Warehouse (Silver/Gold): PostgreSQL
- Transformation: dbt (Data Build Tool)
- API Layer: FastAPI, SQLAlchemy, Pydantic
- ML: scikit-learn, xgboost, lightgbm, catboost, prophet
- Streamlit: web app (data views, operations console)

Pipeline:
SEC + OpenBB/API -> raw PostgreSQL -> normalized features -> rules score + ML -> walk-forward evaluation -> rankings -> Streamlit.

## API

The FastAPI service exposes SEC EDGAR, OpenBB, and combined metrics. `/health`
is public; every other endpoint requires the raw API key in the `X-API-Key`
header:

```bash
# Generate one; do not invent a value by hand. Anything you paste into a README,
# a commit or a chat window is a published secret.
export API_KEY="$(openssl rand -hex 32)"
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Bind to `127.0.0.1` unless you deliberately want the API reachable from other
machines; `0.0.0.0` listens on every interface.

Available routes include `/companies/`, `/companies/{ticker}`,
`/filings/{ticker}`, `/facts/{ticker}`, `/financials/{ticker}`, the
`/openbb/` supplementary routes, and `/metrics/enriched/{ticker}`. The API
service is also available through Docker Compose, published on
`127.0.0.1:8000`; Compose refuses to start it unless `API_KEY` is set (see
[Compose services](#compose-services)).

If SEC has no Company Facts dataset for an issuer, `/facts/{ticker}` returns
HTTP `404` with error code `SEC_COMPANYFACTS_UNAVAILABLE` and the normalized
CIK. This is an expected unavailable-data response, not an API outage.


## Docs

- [SDLC review](docs/sdlc-review.md) — SDLC phase assessment, key roles and
  responsibilities, and prioritized gaps.
- [Requirements](docs/requirements.md) — screening universe, weights, and
  acceptance criteria.
- [Model labeling plan](docs/model-labeling-plan.md) — how the offline ML
  target is populated.
- [Data acquisition](docs/data-acquisition.md) — 12-month dividend lookback,
  nightly accrual, and the post-PoC total-history backfill provision.
- [Nightly verification](docs/nightly-verification.md) — single-owner daily
  check of the 03:00 ET run + data-module audit (`audit.nightly_runs` /
  `audit.nightly_checks`).
- [Deployment runbook](docs/deployment-runbook.md) — release/rollback, secrets,
  nightly schedule (Airflow DAG or systemd).
- [Contributing](CONTRIBUTING.md) — branch model, commits, PR checklist.

## Install

Python and the scripts run where the virtual environment was created. On this
checkout `.venv` is a **Linux venv created in WSL** (it has `bin/`, not
`Scripts/`), and Windows has no Python installed, so `python -m scripts...` in a
Windows PowerShell fails with "Python was not found" before it ever reaches the
database. Use one of these:

- **WSL (recommended here).** Open the Ubuntu terminal and run everything from
  the repository root:

  ```bash
  cd /mnt/d/dividend_equity_crispdm_implementation/dividend_equity_crispdm
  source .venv/bin/activate
  python -m pip install -r requirements-dev.txt
  python -m scripts.init_db
  ```

  Docker publishes PostgreSQL on `127.0.0.1:5432`, which WSL reaches as
  `localhost`, so the default `DATABASE_URL` works unchanged.

- **Native Windows.** Install Python 3.10-3.14 from python.org (not the Microsoft
  Store shortcut), then create a separate environment; do not reuse the WSL
  `.venv`:

  ```powershell
  py -3 -m venv .venv-win
  .venv-win\Scripts\activate
  python -m pip install -r requirements-dev.txt
  python -m scripts.init_db
  ```

On macOS/Linux:

```bash
cd /path/to/dividend_equity_crispdm
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

`requirements.txt` is the runtime set alone and is what the Docker image
installs; `requirements-dev.txt` adds `pytest` and `ruff` on top and is what you
want for the lint and test gates.

To run the pipeline without activating the environment, call the interpreter by
path instead:

```bash
.venv/bin/python -m scripts.run_full_etl
```

## Start PostgreSQL with Docker Compose

Run this from the repository root. With Docker Desktop and WSL, start Docker
Desktop first and enable WSL integration for the distribution. Docker Compose v2
uses `docker compose`; older installations use `docker-compose`.

**`API_KEY` must be set in the shell for every Compose command**, even
`up -d postgres`: Compose interpolates the whole file, and the `api` service
declares it required (`${API_KEY:?...}`), so without it every command fails with
`required variable API_KEY is missing a value`. An exported variable lasts only
for that terminal session, so repeat step 2 in each new terminal. A variable
exported in the shell takes precedence over `API_KEY` in `.env`.

1. Generate a key once and keep it (this is the value clients send as
   `X-API-Key`; never commit it). Skip this if `.env` already has an `API_KEY=`
   line.

   ```bash
   # bash / WSL
   echo "API_KEY=$(openssl rand -hex 32)" >> .env
   ```

   ```powershell
   # PowerShell
   $b = New-Object byte[] 32
   [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
   Add-Content .env ("API_KEY=" + (-join ($b | ForEach-Object { $_.ToString('x2') })))
   ```

2. Export it in the current shell, from the repository root, before any
   `docker compose` command:

   ```bash
   # bash / WSL
   export API_KEY="$(grep '^API_KEY=' .env | cut -d= -f2-)"
   ```

   ```powershell
   # PowerShell
   $env:API_KEY = (Select-String -Path .env -Pattern '^API_KEY=').Line -replace '^API_KEY=', ''
   ```

3. Check that Compose accepts it (prints nothing on success):

   ```bash
   docker compose config --quiet
   ```

   If this reports the missing-variable error, `API_KEY` is not set in this
   terminal; repeat step 2.

To call the API, send the same value in the header:
`curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/companies/`.

If you change the key, recreate the service so it picks it up:
`docker compose up -d --force-recreate api`.

```bash
# Compose v2
docker compose up -d postgres
docker compose ps postgres

# Legacy Compose, if `docker compose` reports an unknown `-d` option
docker-compose up -d postgres
docker-compose ps postgres
```

### Compose services

`docker-compose.yml` defines five services. All published ports are bound to
`127.0.0.1` only, so nothing is reachable from other machines by default; put a
tunnel or authenticating proxy in front if you need that.

| Service | Purpose | Port | Notes |
| --- | --- | --- | --- |
| `postgres` | Warehouse (PostgreSQL 17.11, image pinned by digest) | `127.0.0.1:5432` | Data in the `pgdata` volume; `sql/schema.sql` runs on first initialization only. |
| `migrate` | One-shot `python -m scripts.migrate` | — | `streamlit`, `api` and `worker` wait for it to complete successfully. |
| `streamlit` | Web app (see [Web app](#web-app-streamlit)) | `127.0.0.1:8501` | Read-only unless `OPS_ADMIN_TOKEN` is set. |
| `api` | FastAPI service | `127.0.0.1:8000` | **`API_KEY` is required**; Compose fails fast on any command if it is unset. |
| `worker` | Runs tasks queued from the Operations page and queues schedules (`python -m scripts.ops_worker`) | — | Executes only the commands in `src/crispdm/ops/catalog.py`. Does not schedule the nightly ETL. |

```bash
docker compose up -d          # postgres -> migrate -> streamlit, api, worker
docker compose ps
```

Environment read by Compose (put it in `.env` or export it):

| Variable | Default | Meaning |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `dividend` | Database password. The default is for a loopback-only laptop; change it before the container is reachable by anyone else. If you change it, update `DATABASE_URL` for host-side scripts to match. |
| `API_KEY` | none (required) | Shared key for the API's `X-API-Key` header. Export it in the shell for every Compose command, not just `api` (steps above). |
| `OPS_ADMIN_TOKEN` | empty | Operator sign-in for the web app (12+ characters). Empty = read-only. |
| `SEC_USER_AGENT` | placeholder | Real contact string for SEC requests; the worker's SEC tasks fail while it is the placeholder. |

The `postgres` service is tuned for this warehouse (about 11 GB) on SSD/NVMe
rather than PostgreSQL's defaults: `shared_buffers=2GB`, `work_mem=32MB`,
`maintenance_work_mem=1GB`, `random_page_cost=1.1`,
`effective_io_concurrency=200`, `checkpoint_timeout=15min`, `max_wal_size=4GB`,
and a 512 MB `/dev/shm`. `pg_stat_statements` is loaded, and `log_lock_waits=on`
makes a statement queued behind a lock name its blocker in the log. The
container is capped at `mem_limit: 10g` so PostgreSQL and a peak-memory ETL stage
cannot together exhaust the 24 GB WSL2 VM (`.wslconfig`, memory=24GB); under
pressure the cap costs file cache
rather than triggering an OOM kill. Adjust these in `docker-compose.yml` if your
host or data size differs.

## Initialize the database

Invoke the scripts as Python modules (from the repository root) so the sibling
`src` package is importable:

```bash
python -m scripts.init_db
```

`scripts.init_db` creates the configured database if it does not exist, applies
`sql/schema.sql`, and runs the small compatibility migrations. It reads
`DATABASE_URL` from `.env`, defaulting to:

```text
postgresql+psycopg://dividend:dividend@localhost:5432/dividend
```

## Data Workflow

Run the data-loading stages from the repository root after the database is
initialized. The recommended entrypoint is the orchestrated pipeline:

```bash
# Run from the repository root so the sibling `src` package is importable.
cd /path/to/dividend_equity_crispdm

# Reference tables → dividend data (SEC + OpenBB) → companyfacts/submissions
# → sec_documents concept groups → fundamentals → features → scores/rankings
# → audit. Stage 0 loads standardized SEC ticker and profile summaries for
# dividend payers; stages 2-5 only touch dividend-flagged tickers, so
# non-payers are never requested from SEC or OpenBB. A `migrate --check`
# preflight refuses to start if any migration on disk is unapplied. Every run is
# recorded in audit.nightly_runs for scripts.verify_nightly_run.
python -m scripts.run_full_etl

# Testing/partial runs (stage skips pass through --limit/--tickers/--sources):
python -m scripts.run_full_etl --limit 50
python -m scripts.run_full_etl --tickers ACR-PC,ACR-PD,LFMDP --sources openbb
python -m scripts.run_full_etl --skip-companyfacts --skip-sec-documents

# Skip the offline derived stages (fundamentals, features, scoring, audit)
python -m scripts.run_full_etl --skip-derived
```

Stored SEC companyfacts payloads are re-fetched once they are older than
`--companyfacts-refresh-after-days` (default 5); otherwise a stored CIK would be
skipped forever and its filings frozen at first sighting. Stage 10 (labels) is
opt-in (`--run-labels`) and refused on `--limit`/`--tickers` runs. Run
`python -m scripts.run_full_etl --help` for every flag.

The individual stages behind `run_full_etl`, numbered as `run_full_etl` numbers
them:

```bash
# Stage 0 — Populate raw schema tables with standard attributes based on
# XBRL / Inline XBRL filing tags: raw.company_ticker (SEC company_tickers.json),
# identify dividend payers from SEC Company Facts, persist the per-CIK
# classification cache to raw.company_classification, and fetch a
# raw.ticker_profile summary for each payer (add --skip-profiles to skip)
python -m scripts.populate_raw_tables --limit 100

# Stage 1 — Populate exchanges, issuers, and audited securities from the raw
# ticker universe. Marks dividend = TRUE from SEC company facts, defining the
# dividend universe every later stage is gated on. Recency is enforced (since
# 2026-10-06): a security needs a positive per-share dividend fact whose period
# ends within DIVIDEND_RECENCY_DAYS (548) of the classification date, or a
# payment already observed in raw.dividend_data inside that window. Set
# ENFORCE_DIVIDEND_RECENCY=false to restore the any-positive-fact-ever rule.
python -m scripts.populate_reference_tables --limit 100

# Stage 2 — Daily OHLCV prices into raw.market_data (dividend universe only)
python -m scripts.populate_market_data

# Stage 3 — Load dividend records from SEC XBRL and/or OpenBB, then populate
# preferred.security_terms and raw.ticker_profile summaries. OpenBB starts at
# DIVIDEND_LOOKBACK_START (default 2025-01-01 = the 12-month lookback) and
# accrues forward; add --full-history after the PoC gate for total history.
python -m scripts.populate_dividend_data --tickers ACR-PC,ACR-PD,LFMDP --sources all

# Stage 3a — Rebuild one normalized profile per CIK/ticker. The raw rows and
# all source payloads are retained; conflicting attributes are flagged.
python -m scripts.populate_clean_ticker_profile

# Stage 3b — Split company-level scalar fields from normalized officer rows.
# Epoch fields become UTC dates/timestamps; omitted compensation remains NULL.
python -m scripts.populate_clean_company_profile

# Stage 4 — Load SEC submissions and complete companyfacts (dividend payers
# only by default; add --preferred-facts to target preferred stocks recorded
# in raw.ticker_profile, or --preferred-taxonomy to download taxonomy-scoped
# XBRL concept facts via the SEC XBRL Data API for preferred stocks in
# reference.securities)
python -m scripts.populate_companyfacts --tickers AAPL,MSFT,JNJ
python -m scripts.populate_companyfacts --preferred-facts
python -m scripts.populate_companyfacts --preferred-taxonomy
python -m scripts.populate_companyfacts --preferred-taxonomy --tickers ACR-PC,ACR-PD --taxonomies us-gaap,dei

# Optional preferred-security baseline and taxonomy enrichment. These are not
# run by run_full_etl unless invoked explicitly.
python -m scripts.populate_companyfacts --preferred
python -m scripts.populate_companyfacts --preferred-taxonomy

# Stage 5 — Refresh raw.sec_documents concept-group metadata without new SEC
# requests (dividend payers only by default)
python -m scripts.populate_sec_documents --tickers AAPL,MSFT,JNJ

# Stage 6 — Offline derived financials over stored XBRL (no network)
python -m scripts.populate_fundamentals

# Stages 7-8 — Offline features (model.features) and rule-based scores,
# predictions and rankings (model.scores/predictions/rankings)
python -m scripts.build_features
python -m scripts.score_rank

# Stage 9 — Offline audit lineage/quality over stored data (no network)
python -m scripts.populate_audit

# Stage 10 (optional) — Populate the offline ML target from future dividend
# events once ~12 months of history exists; refused on --limit/--tickers runs
python -m scripts.label_targets
```

Reference-table options are `--exchanges`, `--issuers`, `--securities`, and
`--legacy-sec` (repairs missing issuer fields from the legacy SEC page).
Dividend loading supports `--sources all|sec|openbb`, `--limit`,
`--start-date`, and `--end-date`. **Dividend gating**: every non-reference
stage resolves its target set from `reference.securities WHERE dividend = TRUE
AND active = TRUE` (backed by the `ix_securities_dividend_active` partial
index); explicitly passed `--tickers` are intersected with that universe.
The gate is intentionally strict to prevent probing SEC/OpenBB for securities
that never pay a dividend; force a full sweep only for debugging with
`--all` (`populate_companyfacts`/`populate_sec_documents`) or
`--include-non-dividend` (`populate_dividend_data`).
`populate_dividend_data --limit N` limits the universe itself.

For every equity flagged `dividend = TRUE`, `scripts.populate_raw_tables`
also fetches a **ticker profile summary**, merging SEC Company Facts XBRL
preferred-stock tags (via
`src.crispdm.sec_client.extract_preferred_terms_from_companyfacts`) with a
Yahoo Finance / OpenBB (yfinance provider) fetch, and upserts the result into
`raw.ticker_profile`. SEC XBRL supplies `coupon_rate`
(`PreferredStockDividendRatePercentage`) and `liquidation_preference`
(`PreferredStockLiquidationPreferenceValue` /
`TemporaryEquityLiquidationPreference`, falling back to
`PreferredStockParOrStatedValuePerShare`); when SEC reports them they are
the value `scripts.populate_raw_tables` writes, and the resulting `provider` is
recorded as `SEC_XBRL+OPENBB_YFINANCE` with both sources kept in `raw_payload`.
`scripts.populate_dividend_data` refreshes the same table on later runs
(Yahoo/OpenBB only); pass `--skip-profiles` to
disable its summary fetch and `--skip-preferred-terms` to skip the
`preferred.security_terms` gap-fill. That gap-fill only inserts missing rows
for active preferred securities with dividend records and preserves existing
terms. `scripts.populate_companyfacts --preferred` is a separate baseline
operation: it reads active preferred securities directly from
`reference.securities` and creates or refreshes their baseline
`preferred.security_terms` rows without inventing coupon or redemption terms.
Companyfacts ingestion fetches each unique CIK once and stores the submissions
and XBRL payloads separately; both payloads are issuer-level and kept as a
single CIK-keyed row shared by every linked security.

`--preferred-taxonomy` downloads preferred-stock concept facts (from
`us-gaap` and `dei` by default) through the SEC XBRL Data API
`companyconcept` endpoint for every active
`reference.securities WHERE security_type IN ('preferred', 'preferred stock')` — e.g.
`PreferredStockDividendRatePercentage`,
`PreferredStockLiquidationPreferenceValue`,
`PreferredStockRedemptionPricePerShare`, and
`PreferredStockSharesOutstanding` — and upserts them into
`raw.company_taxonomy` (one row per issuer CIK, `taxonomies` and
`raw_payload` columns keep the per-taxonomy concept lists and full payloads).
Concepts an issuer never filed (HTTP 404) are skipped. The current configured
taxonomy set is `us-gaap,dei`; `ifrs-full` and `srt` are accepted as optional
taxonomies but currently have no configured preferred-stock concepts. Unknown
or zero-concept selections fail fast. Use `--tickers` for a small
preferred-stock run before processing the full universe. The command reports
planned concept requests, processed CIKs,
unavailable concepts, failed CIKs, and missing requested tickers.

The fetched ticker profile summary captures the attributes used by the
preferred-stock screen:

- **Security Type**, e.g. `Series C Preferred Stock (8.625% Fixed-to-Floating)`
- **Coupon Type**, one of `fixed`, `floating`, `fixed-to-floating`
- **Coupon Rate**, e.g. `8.625` (% per annum, first percentage in the name)
- **Fixed Period End**, e.g. `2028-07-30` (parsed from the security name)
- **Floating Spread**, e.g. `5.592` (`...Term SOFR + 5.592%`)
- **Tax Status**, one of `qualified`, `non-qualified`, `tax-exempt`
- **Call Date**, e.g. `7/30/2024 (post-call)` (parsed from the security name)
- **Liquidation Preference / Par**, e.g. `$25` (parsed from the security name)

Yahoo Finance exposes the company profile, sector, and industry; coupon
type, fixed-period end, floating spread, tax status, and call date are
parsed from the security name (best effort and `NULL` when the source text
does not carry them).

`coupon_rate` and `liquidation_preference` have two writers and an explicit
priority rule: **the per-security `dei:SecurityTitle` name parse wins, and SEC
Company Facts XBRL terms are the fallback.**

| source | granularity | precedence | writes |
|---|---|---|---|
| `dei:SecurityTitle` / Yahoo short-name parse | **per security** | primary | stage 0 `populate_raw_tables`, stage 3 `populate_dividend_data` |
| SEC Company Facts XBRL (`PreferredStockDividendRatePercentage`) | **per issuer (CIK)** | fallback | stage 0 `populate_raw_tables` |

The SEC tag is filed once for the whole CIK, so an issuer with several
preferred series (BAC, PSA) publishes one rate that cannot say which series it
belongs to. The companyfacts API omits dimensional (per-series) facts, and
`raw.companyfacts` is keyed by CIK, so nothing here can recover the mapping. The
name parse is per security and therefore more trustworthy in exactly the
multi-series case, and less trustworthy when the cover-page title is unusual —
which is why SEC terms are still worth keeping as a fallback rather than
dropping them.

Stage 0 resolves both sources in one pass and only falls back to the SEC value
when the name parse produced nothing
(`if sec_terms.get("coupon_rate") is not None and summary.get("coupon_rate") is None`).
Stage 3 upserts with `COALESCE(:coupon_rate, coupon_rate)` in both
`raw.ticker_profile` and `reference.securities`, so it can only replace a stored
value when it parses a rate itself. Because neither writer ever overwrites a
good value with a weaker one, the outcome does not depend on which stage ran
first — see `docs/data-health-workstreams.md` before changing either stage.

Each active reference security is normalized by the combination of `cik`,
`ticker`, `security_type`, and `dividend`. Security types are stored as
`common_stock`, `preferred stock`, `debt`, `equity`, `option`, `future`,
`derivative`, `government debt`, `corporate bond`, `other`, `other_debt`,
`other_equity`, or `other_debt_and_equity`. The `dividend` value is true only
when a positive dividend or owner-distribution fact is reported. The columns
`sec_data_status` retains the `available`/`unavailable` classification status
for auditability.

`run_full_etl` already runs these as stages 7-8; to build features and score the
latest feature date by hand after source data is loaded:

```bash
python -m scripts.build_features
python -m scripts.score_rank
```

The ML target (`model.features.target_sustainable_dividend`) is deliberately
never fabricated — populate it from future dividend events
(see [docs/model-labeling-plan.md](docs/model-labeling-plan.md)). When at
least ~12 months of `raw.dividend_data` history exists, populate the offline
label (also available as ETL stage 10 via `run_full_etl --run-labels`, which is
refused on partial `--limit`/`--tickers` runs to keep labels immutable):

```bash
python -m scripts.label_targets
python -m scripts.label_targets --cutoff 2026-12-31   # fixed horizon
python -m scripts.label_targets --rebuild              # careful: overwrites labels
```

Once labeled rows exist, the walk-forward evaluation can be re-run as a diagnostic
(recall gate = `MIN_RECALL`, default 0.30). It has returned NO-GO on every feature
version because the label is 99.6% positive, so the ML model is not adopted and the
rule-based scores are what the app and rankings show:

```bash
python -m scripts.evaluate_walk_forward
```

No data yet? The Go/No-Go mechanism can be demonstrated immediately with an
in-memory synthetic sample (no DB/network writes):

```bash
python -m scripts.dry_run_walk_forward   # -> PASS, writes /tmp/walk_forward_dry_run.json
```

`scripts.label_targets` labels every eligible feature row: **1** if at least
one positive dividend event falls inside the 365-day outcome window, **0** if
the row was monitored through the window end but paid nothing, and leaves
otherwise-eligible rows without post-window monitoring data as NULL
(insufficient evidence).

The current ETL entrypoint for market data is:

```bash
python -m scripts.run_etl --symbols GNL,HMLPF,CMSC --start 2020-01-01
```

The command requires `--symbols` and `--start`; `--end` is optional. It loads
prices and dividends through the configured OpenBB provider.

## Web app (Streamlit)

```bash
streamlit run app/streamlit_app.py --server.address 127.0.0.1   # http://localhost:8501
python -m scripts.ops_worker                # runs queued tasks; needed for the Operations page
```

Pass `--server.address 127.0.0.1` when running Streamlit directly: by default it listens on
every interface. With Docker Compose, `docker compose up -d streamlit worker` starts both. The app
and the worker use the same database as everything else.

| Page | What it does |
| --- | --- |
| Screener | The scored universe as a sortable table with filters (yield, type, score, ticker), charts, CSV download. Selecting a row carries the ticker to Security detail. |
| Security detail | Price history, dividend events by provider, score history, latest features and reported fundamentals for one ticker. |
| Data explorer | Browse an allowlisted set of tables with column choice, up to 8 filters, sorting, a row limit, CSV download and a quick chart. |
| Health | The same checks as `scripts.verify_nightly_run` (freshness against each source's SLA, data quality, dividend coverage, security consistency, walk-forward gate) plus recent nightly runs and their stages. |
| Operations | Queue a task, follow its live log, cancel it, run it again, and create, pause or delete schedules (once, every N minutes, daily in a chosen time zone). |
| Integrations | Database status, API health, an endpoint caller for the FastAPI service, and which providers and secrets are configured (never their values). |

**Operator controls.** Reading is open. Queueing, scheduling, cancelling a task and
calling the API (it uses the server's `API_KEY`) need an operator sign-in. Set
`OPS_ADMIN_TOKEN` to at least 12 characters (see `.env.example`) and restart the app. With
it unset, or shorter, the controls stay off and the app says why; there is no default
token. Five wrong attempts lock sign-in for a minute. The token gates the controls, not
the data, so keep the app on the loopback (Compose publishes it on 127.0.0.1 only) or
behind your own authenticating proxy.

**What the Operations page can run.** Only the tasks in `src/crispdm/ops/catalog.py`
(migration and schema-drift checks, the morning verification, ticker-conflict review,
feature rebuild, scoring, audit refresh, market-data fetch, and a manual full ETL). The
worker rebuilds each command from that list and re-validates the parameters; nothing
typed in the browser is executed as typed, and nothing runs through a shell. Tasks
marked exclusive hold the pipeline lock and so cannot overlap the nightly run or each
other (if it is busy they wait and retry). A schedule never stacks: if its previous task
is still queued or running, that slot is skipped, and a schedule that was missed while
the worker was down fires once and then continues.

The **nightly ETL is still started by the host's systemd timer** (03:00 America/New_York,
see `ops/systemd` and `docs/nightly-verification.md`). The app shows its results on the
Health page; it does not start or stop it.

Start the Streamlit view with:

```bash
streamlit run app/streamlit_app.py
```

The `postgres` container must be running before `scripts.init_db` is executed.
Run all Python commands from the repository root. On Linux or WSL, if Docker
reports `permission denied` for `/var/run/docker.sock`, either add the current
user to the `docker` group and restart the session, or use `sudo` with the
Docker commands:

```bash
sudo usermod -aG docker "$USER"
# Restart WSL or log out and back in before running docker without sudo.
```

If initialization fails, confirm that PostgreSQL is ready before rerunning the
Python command. Use the Compose command variant available on your machine:

```bash
docker-compose exec -T postgres pg_isready --username=dividend --dbname=dividend
python -m scripts.init_db
```

The initializer reports the underlying PostgreSQL error for schema or migration
failures. These are different from a stopped database and should be fixed using
the reported SQL error.

If the configured `dividend` database was dropped, `scripts.init_db` recreates it
through the default PostgreSQL `postgres` database before applying the schema.

## Database Connection

Use the following connection details for the local PostgreSQL instance:

- Server / Host: localhost (or 127.0.0.1)
- Port: 5432
- Database Name: dividend
- Username: dividend
- Password: `dividend` unless you set `POSTGRES_PASSWORD` for Compose
  (the password is applied when the `pgdata` volume is first created; changing
  it later does not alter an existing database)

The container publishes the port on `127.0.0.1` only.

**GUI client on Windows (VS Code PostgreSQL extension, pgAdmin, DBeaver) times out
with "Couldn't reach 'localhost'".** Docker runs inside WSL2, and Windows reaches
it through WSL's localhost forwarding. Two things make `localhost` unreliable
there:

- Windows resolves `localhost` to `::1` first, but the port is published on IPv4
  only, so the first attempt fails and eats part of the client's timeout.
- The first connection after the WSL VM has been idle can take several seconds
  while the forwarder wakes up.

Set the host to `127.0.0.1` (not `localhost`), port `5432`, and raise the
connection timeout to 30 seconds. Check the server side with:

```powershell
Test-NetConnection 127.0.0.1 -Port 5432   # TcpTestSucceeded : True
```

If that fails, confirm the container is healthy
(`docker compose ps postgres` in WSL, with `API_KEY` exported) and that the WSL
VM is running (`wsl -l -v`). The firewall/VPN hints in the client's error message
rarely apply to a loopback port.

## Test the Database Connection

Start the database and verify it is ready:

```bash
docker compose up -d postgres
docker compose exec -T postgres pg_isready --username=dividend --dbname=dividend
```

For legacy Compose, replace `docker compose` with `docker-compose` in the
commands above. The database can be dropped while connected to the default
`postgres` database:

```bash
docker compose exec postgres psql --username=dividend --dbname=postgres --command="DROP DATABASE dividend WITH (FORCE);"
```

You can also test the connection directly from the terminal:

```bash
psql "postgresql://dividend:dividend@localhost:5432/dividend" -c "SELECT version();"
```

The app is configured to use the same value in [src/crispdm/config.py](src/crispdm/config.py):

```text
postgresql+psycopg://dividend:dividend@localhost:5432/dividend
```

## PostgreSQL Database Schema

The database is organized into eight schemas: `raw`, `reference`,
`fundamentals`, `dividends`, `preferred`, `market`, `model`, and `audit`.
`scripts.init_db` applies [sql/schema.sql](sql/schema.sql) (idempotent
`CREATE TABLE IF NOT EXISTS`, plus column-level `COMMENT ON COLUMN` statements
that document the XBRL / Inline XBRL tag behind every normalized attribute) and
then runs the small compatibility migrations in
[scripts/init_db.py](scripts/init_db.py). Those migrations also converge legacy
databases: they de-duplicate the issuer payload tables (keeping one row per CIK
instead of the ~1,000 redundant per-security copies previously written for
issuers with many listed series such as BAC or PSA), re-key
`raw.companyfacts`, `raw.sec_submissions` and `raw.company_taxonomy` on `cik`,
and create `raw.company_classification`.

Changes after that baseline are versioned SQL files in
`sql/migrations/`, applied in order by `scripts.migrate` and recorded in the
`schema_migrations` table.

- `python -m scripts.migrate --check` reports whether any migration is pending. It
  compares the ledger, so it cannot see an object that was altered outside the
  migration runner.
- `python -m scripts.check_schema_drift` answers the other question — whether the
  database matches the repository at all. It builds a scratch database from
  `sql/schema.sql`, the inline migrations in `scripts/init_db.py` and every
  versioned migration, then diffs that against the live catalog. Exit status 0
  means they agree. It is not a stage preflight: it creates and drops a database,
  so run it deliberately when deploying.

### reference — master data

| Table | Purpose | Key columns |
|---|---|---|
| `reference.exchanges` | US exchange codes | `exchange_id` PK, `exchange_code`, `exchange_name` |
| `reference.issuers` | SEC issuer metadata | `issuer_id` PK, `cik`, `issuer_name`, `sic`, `fiscal_year_end` |
| `reference.securities` | Audited security rows built from SEC tickers + Company Facts | `security_id` UUID PK, `ticker`, `cik`, `issuer_id` FK, `security_name`, `security_type`, `coupon_rate`, `dividend`, `dividend_last_paid`, `sec_data_status`, `cusip`, `isin`, `exchange_id` FK, `currency`, `liquidation_preference`, `call_date`, `active`; unique index `(cik, ticker, security_type, dividend)` |

`reference.securities` is the hub of the model: every table references its
`security_id`. `security_type` is one of `common_stock`, `preferred stock`,
`debt`, `equity`, `option`, `future`, `derivative`, `government debt`,
`corporate bond`, `other`, `other_debt`, `other_equity`,
`other_debt_and_equity`. `dividend` is `TRUE` only when a positive dividend or
owner-distribution fact was reported.

The issuer name is normalized onto `reference.issuers.issuer_name`
(`dei:EntityRegistrantName`); `reference.securities` references it through
`issuer_id` / `cik` instead of duplicating the text per security row.
`reference.securities.security_name` holds the per-class cover title exactly as
reported on the Form 8-K / annual-report cover for that ticker (e.g.
`7.875% Series D Cumulative Redeemable Preferred Stock` for ACR-PD), sourced
from `raw.sec_instrument_titles`.

### clean — consolidated profiles

| Table | Purpose | Key columns |
|---|---|---|
| `clean.ticker_profile` | One normalized row per `(CIK, ticker)`, rebuilt after raw profile writers; consensus values only, with classification/attribute conflicts and all contributing raw payloads retained | PK `(cik, ticker)`, representative `security_id`, `source_security_ids`, `profile_count`, `provider_sources`, normalized profile attributes, `metadata_conflicts`, `source_profiles` |

The representative security is chosen by active status, classifier confidence,
then evidence priority. Conflicting liquidation preferences are left NULL and
reported in `metadata_conflicts`; the raw source rows are never deleted.

| Table | Purpose | Key columns |
|---|---|---|
| `clean.company_profile` | Typed company-level provider snapshot, one row per symbol and parent name | `symbol`, `parent_name`, `reference_security_id`, scalar provider attributes, `source_payload`, generated `c2_c3_leverage_exempt` |
| `clean.company_officer` | One child row per officer in the provider’s company-officers array | composite FK `(symbol, parent_name)`, `officer_no`, officer attributes, nullable `total_pay` |

The `c2_c3_leverage_exempt` tag marks `issue_type = EQUITY` and `sector_key = real-estate` for downstream review only; it does not modify C2/C3 scoring. Unix epoch date fields are stored as UTC `DATE`/`TIMESTAMPTZ`; the loader detects seconds versus milliseconds by magnitude. The invalid SQL identifier `52_week_change` is exposed as `pct_change_52w` while preserved in source payload metadata. Officer rows use `(symbol, parent_name, officer_no)` as their load key and a NULL-aware unique identity on `(symbol, parent_name, name, title)` to prevent repeat ingestion.

### raw — ingested source payloads

| Table | Purpose | Key columns |
|---|---|---|
| `raw.company_ticker` | SEC `company_tickers.json` snapshot | `ticker` PK, `cik`, `title`, `raw_payload`; unique `(ticker, cik)` |
| `raw.market_data` | Daily OHLCV prices | PK `(security_id, observation_date, provider)`, `open/high/low/close/adjusted_close`, `volume` |
| `raw.dividend_data` | Normalized dividend events | PK `(security_id, ex_dividend_date, provider)`, `declaration_date`, `record_date`, `payment_date`, `amount`, `adjusted_amount`, `frequency`, `currency` |
| `raw.ticker_profile` | **Ticker profile summary** for every dividend payer, driven from `raw.company_ticker` (Security Type, Coupon Type/Rate, Fixed Period End, Floating Spread, Tax Status, Call Date, Liquidation Preference); `coupon_rate`/`liquidation_preference` come from SEC Company Facts XBRL tags when reported, else Yahoo/OpenBB or name parsing | `security_id` PK, `ticker`, provider, `coupon_type`, `coupon_rate`, `fixed_period_end`, `floating_spread`, `tax_status`, `call_date`, `liquidation_preference`, `raw_payload` |
| `raw.companyfacts` | Full XBRL company facts, fetched once per issuer CIK | `cik` PK, `company_name`, `concept_groups` (JSONB), `raw_payload` (JSONB), `content_hash`, `provider` |
| `raw.company_taxonomy` | Taxonomy-scoped XBRL concept facts (preferred-stock tags) via the SEC XBRL Data API `companyconcept` endpoint, fetched once per issuer CIK | `cik` PK, `company_name`, `taxonomies` (JSONB), `concept_groups` (JSONB), `raw_payload` (JSONB), `content_hash`, `provider` |
| `raw.company_classification` | Compact per-CIK cache of `classify_companyfacts()`; persisted by stage 0 and consumed by stages 1/3 so the full companyfacts JSON is downloaded at most once per run | `cik` PK, `ticker`, `company_name`, `security_types` (JSONB), `security_facts` (JSONB), `dividend_facts` (JSONB), `dividend`, `status`, `content_hash` |
| `raw.sec_submissions` | SEC submissions history, fetched once per issuer CIK | `cik` PK, `company_name`, `raw_payload` (JSONB), `content_hash`, `provider` |
| `raw.sec_documents` | Extracted filing documents and per-security XBRL concept groups | `document_id` PK, `security_id` FK (one row per security), `accession_no`, `form_type`, `primary_document`, `concept_groups` (JSONB), `content_hash`, `raw_text`. Unique partial index `ux_sec_documents_security(security_id)`; `concept_groups` refreshed by `populate_sec_documents` |

The issuer-level payload tables (`raw.companyfacts`, `raw.company_taxonomy`,
`raw.sec_submissions`) are keyed by `cik`: the SEC submissions and companyfacts
JSON describe the issuer, so one row per CIK is fetched and stored, and every
listed security of that issuer links to it through `reference.securities.cik`.
This removed ~1,003 duplicate copies per payload table (the loaded
`companyfacts` table dropped from 4,354 to 3,351 rows / ~514 MB reclaimed) and
the `raw.company_classification` cache prevents the same full JSON from being
re-downloaded by the reference and companyfacts stages.

`reference.securities` keeps a partial index `ix_securities_dividend_active
(ticker) WHERE dividend = TRUE AND active = TRUE` that defines the dividend
universe used by every downstream ETL stage, so SEC and OpenBB are queried
only for dividend-flagged securities.

When `ENFORCE_DIVIDEND_RECENCY` is on (the default), `dividend = TRUE` requires a positive
dividend fact whose period ends within `DIVIDEND_RECENCY_DAYS` (548 days,
`src/crispdm/xbrl_tags.py`) of the classification date. SEC XBRL Company Facts
retain every fact an issuer has ever filed, including comparative columns from
long-past periods, so an unbounded "has any positive dividend fact" test kept
long-defunct and acquired issuers in the universe indefinitely. 548 days is the
same horizon the preferred dividend snapshot uses, so the reference universe and
the per-instrument snapshot agree on what "currently paying" means. The
qualifying period end is stored in `reference.securities.dividend_last_paid`,
and `classification_evidence` records `dividend_lookback_start`, so a flag can
always be traced to the fact that set it.

Enforcement is **on by default** (`enforce_dividend_recency` in
`src/crispdm/config.py`, decision 2026-10-06). The tag test alone is weak: any
concept whose name contains "dividend" counts, including dividends *received*,
payables and balance-sheet items, so a recent tag is not proof the issuer pays.
Since 2026-10-07 the classification therefore only sets `dividend = TRUE` from a
positive **per-share** declared/paid fact (`CommonStockDividendsPerShare*`,
`PreferredStockDividendsPerShare`, IFRS `CashDividendsPerShare*`); aggregate
paid/payable balances and investor-side received-amount concepts
(`InterestAndDividendIncomeOperating`, `EquityMethodInvestmentDividendsOrDistributions`)
are kept in the audit evidence but cannot flag an issuer. A security with a
positive payment in `raw.dividend_data` inside the same 548-day window also stays
flagged (`src/crispdm/dividend_universe.py`, applied in both
`populate_raw_tables` and `populate_reference_tables`). The payment
arm only keeps an existing payer: dividends are fetched only for flagged securities,
so a new one must be found by its tags. A security that drops out is deactivated, not
deleted, and returns with its history if it pays again. Turning enforcement off
restores the any-fact-ever rule on the next stage 0 and 1 run.

`raw.ticker_profile` columns populated by SEC Company Facts XBRL
(`coupon_rate` as the fallback source, `liquidation_preference`, prioritized
when reported) merged
with a Yahoo Finance / OpenBB (yfinance provider) profile fetch plus
best-effort parsing of the security name (keys left `NULL` when no source
carries them):

```text
security_id, ticker, provider, sector, industry, security_type,
coupon_type (fixed | floating | fixed-to-floating),
coupon_rate, fixed_period_end, floating_spread,
tax_status (qualified | non-qualified | tax-exempt),
call_date, liquidation_preference (par), raw_payload (JSONB), retrieved_at
```

### preferred — enriched security terms

| Table | Purpose | Key columns |
|---|---|---|
| `preferred.security_terms` | Preferred-stock legal/economic terms | `security_id` PK, `preferred_series`, `dividend_rate`, `liquidation_preference`, `confidence_score`, `reviewed_by` |
| `preferred.dividend_snapshot` | Preferred issuers with dividend evidence (built by `scripts.sec_xbrl_dividend_tags`); `active=False` flags issuers whose latest dividend fact falls outside the lookback window | `security_id` PK, `ticker`, `cik`, `preferred_flag`, `pays_dividend`, `active`, `dividend_evidence_tag`, `latest_dividend_period_end/filed/form` |
| `preferred.issuer_terms` | **View.** SEC XBRL preferred terms at *issuer* granularity, recovered from `raw.ticker_profile.raw_payload->sec_xbrl` where `populate_preferred_profiles` parks them. Exists because Company Facts carry no series dimension, so these values are deliberately **not** promoted into `clean.ticker_profile`'s per-series columns | `cik` (grouping key), `issuer_name`, `issuer_coupon_rate_pct`, `issuer_liquidation_or_par_value`, `security_count`, `distinct_coupon_values`, `distinct_liquidation_values`, `terms_scope` (constant `issuer_level_unallocated`) |

Rows are seeded by the dividend stage's preferred-term gap-fill and by
`scripts.populate_companyfacts --preferred`. The dividend-stage gap-fill uses
`ON CONFLICT DO NOTHING`; the reference-driven baseline preserves existing
preferred series and cumulative values. Both paths leave researched economic
terms intact, and rows can be enriched manually via
`scripts.yahoo_FetchPreferredStock.py`.

### XBRL / Inline XBRL tag registry

Every normalized attribute in the dividend tables maps to one or more SEC
XBRL / Inline XBRL (iXBRL) filing tags. That mapping lives in one place —
[src/crispdm/xbrl_tags.py](src/crispdm/xbrl_tags.py) — so the schema column
comments, the ETL extractors, the fact classifiers, and the taxonomy loaders
stay in sync and the same economic fact is never re-loaded under a different
name. The tag prefixes are `dei` (Document and Entity Information), `us-gaap`
(US GAAP facts), `srt` (Standard registrant taxonomy), and `ix`/`xbrl`
(iXBRL filing markers).

| Attribute (table column) | Canonical XBRL / iXBRL tags |
|---|---|
| `reference.securities.ticker` | `dei:TradingSymbol` |
| `reference.securities.cik` | `dei:EntityCentralIndexKey` |
| `reference.issuers.issuer_name` | `dei:EntityRegistrantName` |
| `reference.securities.security_name` | `dei:SecurityTitle`, `dei:Security12bTitle` (per-class cover title, e.g. `7.875% Series D Cumulative Redeemable Preferred Stock`) |
| `reference.securities.cusip` / `isin` | `us-gaap:CUSIP`, `srt:ISIN` (fallbacks `us-gaap:DebtInstrumentCusip`, `us-gaap:ISIN`) |
| `coupon_rate` (`reference.securities`, `raw.ticker_profile`) | `us-gaap:PreferredStockDividendRatePercentage`, fallback `us-gaap:PreferredStockDividendRatePerAnnum` (both per-CIK, so ambiguous for multi-series issuers); OpenBB/yfinance or `dei:SecurityTitle` name parse (per security) — last writer wins, see the two-writer note above |
| `liquidation_preference` (`reference.securities`, `raw.ticker_profile`) | `us-gaap:PreferredStockLiquidationPreferenceValue` → `...Preference` → `TemporaryEquityLiquidationPreference(Value)`; fallback `us-gaap:PreferredStockParOrStatedValuePerShare`, then name parse |
| `par_value` | `us-gaap:PreferredStockParOrStatedValuePerShare`, `us-gaap:TemporaryEquityParOrStatedValuePerShare` |
| `raw.dividend_data.amount` | per-share: `us-gaap:CommonStockDividendsPerShareDeclared`, `us-gaap:CommonStockDividendsPerShareCashPaid`, `us-gaap:PreferredStockDividendsPerShare`; aggregate fallbacks `DividendsCommonStockCash`, `PaymentsOfDividendsCommonStock`, `PaymentsOfDividendsPreferredStock`, `DividendsPreferredStockCash`, `PaymentsOfDividends`, `Dividends` |
| `raw.dividend_data.ex_dividend_date` | `xbrl:periodEnd` (the concept `end` date is the proxy; SEC XBRL has no ex-date fact) |
| `raw.dividend_data.declaration_date` / `record_date` / `payment_date` | `ix:declarationDate`, `ix:recordDate`, `ix:paymentDate` — iXBRL filing narrative, not companyfacts facts |
| `raw.dividend_data.frequency` / `currency` | inferred / derived from the XBRL unit, not standalone us-gaap facts |
| security class (`reference.securities.security_type`) | `SECURITY_FACT_RULES` — normalized concept-name rules (e.g. `commonstock`, `preferredstock`, `debt`/`borrowings`, `stockholdersequity`) |
| dividend evidence (`reference.securities.dividend`, `preferred.dividend_snapshot.pays_dividend`) | `DIVIDEND_FACT_TERMS` — concepts containing `dividend` or `distributionstoowners` with positive reported values |
| `preferred.security_terms.dividend_rate` | `us-gaap:PreferredStockDividendRatePercentage` (seeded from the latest `raw.dividend_data` amount when no XBRL rate was filed) |
| `raw.ticker_profile.call_date` | parsed from `dei:SecurityTitle` (`...RedemptionPricePerShare` supplies the price, not the date) |
| `raw.ticker_profile.coupon_type` / `fixed_period_end` / `floating_spread` / `tax_status`, `preferred.security_terms.preferred_series` | parsed from `dei:SecurityTitle` / iXBRL filing language, not standalone us-gaap facts |
| `clean.ticker_profile.coupon_rate` / `coupon_type` / `fixed_period_end` / `floating_spread` / `tax_status` / `call_date` / `liquidation_preference` | consensus of `raw.ticker_profile`, which is **NULL for almost every row by design**, not by failure. Two independent causes: (1) the name-based parsers match almost nothing — over all 11,659 `reference.securities` names, `coupon_rate` matches 0.3% and `call_date` / `fixed_period_end` / `floating_spread` / `tax_status` match **0%**; (2) the rich SEC XBRL terms are issuer-level and are quarantined in `raw.ticker_profile.raw_payload->sec_xbrl` rather than assigned to a series (see `preferred.issuer_terms`). ~67% of `clean.ticker_profile` is `common_stock`, where these fields are not applicable |
| `raw.company_taxonomy` | preferred-stock concepts fetched once per CIK via the XBRL Data API `companyconcept` endpoint (`PREFERRED_STOCK_TAXONOMY_CONCEPTS`) |

The tag lists used by each extractor (`DIVIDEND_TAGS`,
`SEC_DIVIDEND_CONCEPTS`, `PREFERRED_COUPON_CONCEPTS`,
`PREFERRED_LIQUIDATION_CONCEPTS`, `PREFERRED_PAR_VALUE_CONCEPTS`,
`PREFERRED_REDEMPTION_CONCEPTS`, `PREFERRED_STOCK_TAXONOMY_CONCEPTS`,
`DEI_TAXONOMY_CONCEPTS`, `SECURITY_FACT_RULES`, `DIVIDEND_FACT_TERMS`) are
imported from the registry by `src.crispdm.sec_client` and the ETL scripts, so
there are no duplicated tag sets left in the codebase.

### fundamentals / model / audit — analysis layers

| Table | Purpose |
|---|---|
| `fundamentals.periodic_financials` | Normalized financial statements, PK `(security_id, period_end, fiscal_period)` |
| `model.features` | Derived dividend-model features, PK `(security_id, as_of_date)` |
| `model.scores` | Rule/ML scores, PK `(security_id, as_of_date)` |
| `model.predictions` | Model predictions per run, PK `(run_id, security_id, as_of_date)` |
| `model.rankings` | Final ranked output, PK `(security_id, as_of_date)` |
| `audit.source_lineage` | Field-level provenance (`field_name`, `field_value`, `source`, `period`) |
| `audit.data_quality` | Per-security quality scores, PK `(security_id, as_of_date)` |
| `audit.model_runs` | Model run metadata and metrics |

## Dataflow

```text
SEC company tickers / EDGAR ────────────────► raw.company_ticker
                                                  │
SEC issuer metadata / OpenBB profile ────────────┤
                                                  ▼
SEC Company Facts (XBRL) ─────────────────► reference.securities  (classified type + dividend flag)
                                                  │
                                    dividend universe (ix_securities_dividend_active)
                                    = securities WHERE dividend=TRUE AND active=TRUE
                                    │  stages below only process this set
      ┌──────────────┬───────────────┴────────────────┬───────────────┬───────────────┐
      ▼              ▼                                ▼               ▼               ▼
raw.sec_submissions  raw.companyfacts       raw.company_taxonomy       raw.dividend_data
raw.sec_documents    (complete XBRL facts)  (preferred XBRL facts)      (SEC XBRL + OpenBB)
raw.company_classification (per-CIK classify cache)
      │                       │
      └─ issuer payloads are keyed by CIK: ONE row fetched once per issuer,
         shared by every linked security through reference.securities.cik
      └─ concept_groups refreshed from stored XBRL without new SEC requests

raw.ticker_profile ◄── SEC Company Facts XBRL (coupon_rate, liquidation_preference)
                    merged with OpenBB/yfinance profile summaries
preferred.security_terms ◄── dividend-stage gap-fill or --preferred baseline
                    (existing researched terms are preserved)

raw.market_data ◄── OpenBB historical prices
fundamentals.periodic_financials ◄── SEC financial statements

model.features ◄── scripts.build_features
model.scores / model.rankings ◄── scripts.score_rank
Streamlit app ◄── model.rankings + raw data (app/streamlit_app.py)
ops.tasks / ops.schedules ◄── Operations page ──► scripts.ops_worker runs them
```

End to end, the pipeline is: **SEC + OpenBB → raw PostgreSQL → normalized
features → rules score + ML → walk-forward evaluation → rankings →
Streamlit**. Every raw table keeps its original JSON in `raw_payload` with
content hashes, provider tags, and timestamps so each transformation is
auditable through `audit.source_lineage`.

## SEC Data Model

This project uses the official SEC company tickers data from:
**https://www.sec.gov/files/company_tickers.json**

The response is stored in `raw.company_ticker` with the SEC ticker as its
primary key. CIK is not globally unique because one issuer can have multiple
listed tickers, such as `GOOG` and `GOOGL`. `reference.securities` is built
from this raw table; its ticker is the primary key and `(ticker, cik)` links
back to the SEC ticker record.

The [src/crispdm/sec_client.py](src/crispdm/sec_client.py) module provides utilities to work with this data:

### Functions

- `get_company_tickers()`: Fetch all company tickers from SEC source
- `ticker_to_cik(ticker)`: Look up CIK number by ticker symbol
- `cik_to_ticker(cik)`: Look up ticker symbol by CIK number

### Usage

```python
from src.crispdm.sec_client import ticker_to_cik, cik_to_ticker, get_company_tickers

# Look up CIK by ticker
cik = ticker_to_cik("AAPL")  # Returns: 320193

# Look up ticker by CIK
ticker = cik_to_ticker(320193)  # Returns: 'AAPL'

# Get all available company tickers
all_tickers = get_company_tickers()
print(f"Total companies: {len(all_tickers)}")
```

## SEC Submissions and Companyfacts Flow

The pipeline stores the two SEC payload types separately:

- `raw.sec_submissions`: issuer metadata and filing history from
    `https://data.sec.gov/submissions/CIK{cik}.json`
- `raw.companyfacts`: complete XBRL facts from
    `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`

Both tables retain the original JSON in `raw_payload`, along with the CIK,
content hash, provider, and retrieval timestamp. Because both payloads describe
the issuer rather than one listed series, each is stored as a single row keyed
by `cik` (the primary key) and shared by every linked security — never copied
once per security. `raw.companyfacts` also stores the grouped concept names used
by downstream processing. Taxonomy-scoped preferred-stock concept facts are
stored the same way in `raw.company_taxonomy`, loaded by
`python -m scripts.populate_companyfacts --preferred-taxonomy`
(see the Stage 4 example above).

`scripts.populate_raw_tables` additionally persists the result of
`classify_companyfacts()` for each CIK into `raw.company_classification`; stage
1 (`populate_reference_tables`) and stage 4 (`populate_companyfacts`) read that
cache instead of downloading the full companyfacts JSON again, so the same
issuer payload is requested from SEC at most once per pipeline run.

Use the XBRL companyfacts endpoint for a single company when inspecting all
reported concepts:

```python
from src.crispdm.sec_client import get_companyfacts_concepts

# Fetch the full payload and all concept families for one company
company = get_companyfacts_concepts(320193)  # Apple
print(company["company"])
print(company["concept_groups"]["dividends"][:10])
print(company["concept_groups"]["earnings"][:5])
print(company["concept_groups"]["cash_flow"][:5])
print(company["concept_groups"]["balance_sheet"][:5])
print(company["concept_groups"]["debt"][:5])
print(company["concept_groups"]["tax"][:5])
print(company["concept_groups"]["share_counts"][:5])

```

This calls the SEC endpoint:

```text
https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
```

The upstream companyfacts process loads all XBRL concepts for the company, including:

- dividends
- earnings
- cash flow
- balance sheet
- debt
- tax
- share counts

The separate submissions loader and companyfacts loader preserve the complete
payloads. Dividend concepts are not used to exclude a company from storage;
they remain available in the grouped concept metadata for later processing.

## Ingesting Complete Companyfacts

Run the combined process after `reference.securities` has been populated:

```bash
# Refresh selected companies
python -m scripts.populate_companyfacts --tickers AAPL,MSFT,JNJ

# Refresh all SEC ticker records that match active securities
python -m scripts.populate_companyfacts
```

For each matching SEC ticker, the process fetches each unique CIK once from
both SEC endpoints, upserts the submissions payload into `raw.sec_submissions`,
and upserts the complete XBRL payload into `raw.companyfacts`. Multiple tickers
for the same issuer reuse the cached SEC responses and share the single
CIK-keyed row: the payload is stored exactly once and reference securities link
to it through their `cik` column. Re-running the process skips CIKs already
stored and updates existing rows using stable content hashes.

For preferred stocks (`reference.securities WHERE active = TRUE AND
security_type IN ('preferred', 'preferred stock')`), taxonomy-scoped concepts
are fetched once per normalized CIK through the XBRL Data API `companyconcept`
endpoint. The resulting issuer payload is upserted into a single CIK-keyed
`raw.company_taxonomy` row shared by every linked preferred security. HTTP 404
responses for concepts the issuer never reported are expected and skipped; other
request or storage failures are reported as run errors and do not replace a
prior successful taxonomy snapshot.

To refresh the concept-group index from stored XBRL payloads without making
SEC requests, run:

```bash
python -m scripts.populate_sec_documents
```

For model training, the production target must be populated from future dividend events/financial coverage before training; the starter code deliberately does not fabricate labels.