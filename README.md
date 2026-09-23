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
- Orchestration: scripts.run_full_etl (stages 0-4); Apache Airflow optional
- Data Lake (raw): PostgreSQL (Dockerized, localhost)
- Data Warehouse (Silver/Gold): PostgreSQL
- Transformation: dbt (Data Build Tool)
- API Layer: FastAPI, SQLAlchemy, Pydantic
- ML: scikit-learn, xgboost, lightgbm, catboost, prophet
- Streamlit: web app

Pipeline:
SEC + OpenBB/API -> raw PostgreSQL -> normalized features -> rules score + ML -> walk-forward evaluation -> rankings -> Streamlit.

## API

The FastAPI service exposes SEC EDGAR, OpenBB, and combined metrics. `/health`
is public; every other endpoint requires the raw API key in the `X-API-Key`
header:

```bash
export API_KEY="0a1b2c3d4e5f6g7h"
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Available routes include `/companies/`, `/companies/{ticker}`,
`/filings/{ticker}`, `/facts/{ticker}`, `/financials/{ticker}`, the
`/openbb/` supplementary routes, and `/metrics/enriched/{ticker}`. The API
service is also available through Docker Compose on port `8000`; set `API_KEY`
before running `docker compose up -d api`.

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
- [Deployment runbook](docs/deployment-runbook.md) — release/rollback, secrets,
  nightly schedule (Airflow DAG or systemd).
- [Contributing](CONTRIBUTING.md) — branch model, commits, PR checklist.

## Install

```bash
cd /path/to/dividend_equity_crispdm
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

On WSL/Linux, this repository also includes a checked-in `venv` used by the
current workspace. Activate it before running the ETL so `python3` does not
resolve to the system interpreter without project dependencies:

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.run_full_etl
```

The equivalent non-activated form is `venv/bin/python -m
scripts.run_full_etl`.

## Start PostgreSQL with Docker Compose from the repository root. 
With Docker Desktop and WSL, start Docker Desktop first and enable WSL integration for the
distribution. Docker Compose v2 uses `docker compose`; older installations use
`docker-compose`:

```bash
# Compose v2
docker compose up -d postgres
docker compose ps postgres

# Legacy Compose, if `docker compose` reports an unknown `-d` option
docker-compose up -d postgres
docker-compose ps postgres
```

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
# → sec_documents concept groups. Stage 0 loads raw standardized on SEC tickers and profile
# summaries for dividend payers; stages 2-4 only touch dividend-flagged 
# tickers, so non-payers are never requested from SEC or OpenBB.
python -m scripts.run_full_etl

# Testing/partial runs (stage skips pass through --limit/--tickers/--sources):
python -m scripts.run_full_etl --limit 50
python -m scripts.run_full_etl --tickers ACR-PC,ACR-PD,LFMDP --sources openbb
python -m scripts.run_full_etl --skip-companyfacts --skip-sec-documents
```

The individual stages behind `run_full_etl`:

```bash
# Stage 0 — Populate raw schema tables with standard attributes based on
# XBRL / Inline XBRL filing tags: raw.company_ticker (SEC company_tickers.json),
# identify dividend payers from SEC Company Facts, persist the per-CIK
# classification cache to raw.company_classification, and fetch a
# raw.ticker_profile summary for each payer (add --skip-profiles to skip)
python -m scripts.populate_raw_tables --limit 100

# Stage 1 — Populate exchanges, issuers, and audited securities from the raw
# ticker universe. Marks dividend = TRUE from SEC company facts, defining the
# dividend universe every later stage is gated on.
python -m scripts.populate_reference_tables --limit 100

# Stage 2 — Load dividend records from SEC XBRL and/or OpenBB, then populate
# preferred.security_terms and raw.ticker_profile summaries
python -m scripts.populate_dividend_data --tickers ACR-PC,ACR-PD,LFMDP --sources all

# Stage 3 — Load SEC submissions and complete companyfacts (dividend payers
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

# Stage 4 — Refresh raw.sec_documents concept-group metadata without new SEC
# requests (dividend payers only by default)
python -m scripts.populate_sec_documents --tickers AAPL,MSFT,JNJ
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
`PreferredStockParOrStatedValuePerShare`); those values take priority over
the Yahoo/OpenBB or name-parsed equivalents when SEC reports them, and the
resulting `provider` is recorded as `SEC_XBRL+OPENBB_YFINANCE` with both
sources kept in `raw_payload`. `scripts.populate_dividend_data` refreshes the
same table on later runs (Yahoo/OpenBB only); pass `--skip-profiles` to
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
does not carry them). `coupon_rate` and `liquidation_preference` prefer the
SEC Company Facts XBRL tags read by
`extract_preferred_terms_from_companyfacts` and fall back to the name-parsed
value only when the issuer never reported the concept.

Each active reference security is normalized by the combination of `cik`,
`ticker`, `security_type`, and `dividend`. Security types are stored as
`common_stock`, `preferred stock`, `debt`, `equity`, `option`, `future`,
`derivative`, `government debt`, `corporate bond`, `other`, `other_debt`,
`other_equity`, or `other_debt_and_equity`. The `dividend` value is true only
when a positive dividend or owner-distribution fact is reported. The columns
`sec_data_status` retains the `available`/`unavailable` classification status
for auditability.

Build features and score the latest feature date after source data is loaded:

```bash
python -m scripts.build_features
python -m scripts.score_rank
```

The ML target (`model.features.target_sustainable_dividend`) is deliberately
never fabricated — populate it from future dividend events first
(see [docs/model-labeling-plan.md](docs/model-labeling-plan.md), a
`scripts.label_targets` job is planned). Once labeled rows exist, record the
walk-forward evaluation checkpoint (the Azure Go/No-Go, recall gate =
`MIN_RECALL`, default 0.30) with:

```bash
python -m scripts.evaluate_walk_forward
```

The current ETL entrypoint for market data is:

```bash
python -m scripts.run_etl --symbols GNL,HMLPF,CMSC --start 2020-01-01
```

The command requires `--symbols` and `--start`; `--end` is optional. It loads
prices and dividends through the configured OpenBB provider.

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
- Password: dividend

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

### reference — master data

| Table | Purpose | Key columns |
|---|---|---|
| `reference.exchanges` | US exchange codes | `exchange_id` PK, `exchange_code`, `exchange_name` |
| `reference.issuers` | SEC issuer metadata | `issuer_id` PK, `cik`, `issuer_name`, `sic`, `fiscal_year_end` |
| `reference.securities` | Audited security rows built from SEC tickers + Company Facts | `security_id` UUID PK, `ticker`, `cik`, `issuer_id` FK, `security_name`, `security_type`, `coupon_rate`, `dividend`, `sec_data_status`, `cusip`, `isin`, `exchange_id` FK, `currency`, `liquidation_preference`, `call_date`, `active`; unique index `(cik, ticker, security_type, dividend)` |

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

`raw.ticker_profile` columns populated by SEC Company Facts XBRL
(`coupon_rate`, `liquidation_preference`, prioritized when reported) merged
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
| `coupon_rate` (`reference.securities`, `raw.ticker_profile`) | `us-gaap:PreferredStockDividendRatePercentage`, fallback `us-gaap:PreferredStockDividendRatePerAnnum`; else OpenBB/yfinance or name parse |
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
Oracle company tickers / SEC data ─────────► raw.company_ticker
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
(see the Stage 3 example above).

`scripts.populate_raw_tables` additionally persists the result of
`classify_companyfacts()` for each CIK into `raw.company_classification`; stage
1 (`populate_reference_tables`) and stage 3 (`populate_companyfacts`) read that
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