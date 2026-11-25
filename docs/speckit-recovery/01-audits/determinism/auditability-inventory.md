# Stage 1D Auditability Inventory

| Field | Value |
|---|---|
| Stage | 1D — Determinism and auditability |
| Scope | What the warehouse and artifacts record, what can be reconstructed, what cannot |
| Method | Schema read, writer read, SELECT-only probes; no writes |
| Repo HEAD | `d748cea` |
| Date | 2026-11-15 |

**Definitions used here**

- **Source evidence** — the payload/value as received, with a retrieval timestamp.
- **Run identity** — an identifier that groups every row written by one invocation.
- **Code identity** — a git SHA (and dirty flag) or image digest that produced the row.
- **Data identity** — a snapshot/hash/version of the inputs read by the run.
- **Reconstructable** — a past state can be rebuilt from stored evidence plus current code.
- **Audit-reproducible** — the same computed result can be regenerated and verified, including code, data, config, and environment.

## 1. Store-by-Store Audit

| Store | Key | Source evidence kept | Run id | Code/data stamp | Overwrite/history | Reconstructable | Finding |
|---|---|---|---|---|---|---|---|
| `raw.market_data` | `(security_id, observation_date, provider)` | Current prints only; 9,823,774 rows, provider `OPENBB` only | No | No | Latest-only per key; no revisions | Partially: current values only | DA-08 |
| `raw.dividend_data` | `(security_id, ex_dividend_date, provider)` | Current row; 323,632 rows (OPENBB 197,179, SEC_XBRL 126,453) | No | No | Upsert replaces dates/amounts (DA-05) | No for overwritten dates | DA-05 |
| `raw.dividend_amount_check` | `(ticker, ex_dividend_date)` | Latest FMP/Yahoo/Polygon figures; 354 unresolved, 171 fmp, 52 yfinance | No | No | Upsert replaces verdict and `checked_at` | No | DA-06 |
| `raw.dividend_calendar` | Calendar event key | Current event; 2,121 rows | No | No | No delete/withdrawal; overwrite on conflict | No for cancelled/rescheduled events | DA-15 |
| `raw.upcoming_dividends` | View | Derived from calendar | — | — | `CURRENT_DATE` only | No as-of view | DA-15, DA-20 |
| `raw.companyfacts` | `cik` | Current payload; 7,177 CIKs | No | No | Latest-only; old payload lost on change | Partially: embedded `filed` vintages may allow model PIT rebuild | DA-03 |
| `raw.sec_submissions` | `cik` | Current payload; 8,208 CIKs | No | No | Latest-only | No | DA-03 |
| `raw.ticker_profile` / `_load` | Projection / `load_id` | Append-only history; 210,009 load rows | Loader label, not run id | No | Load history retained | Yes, profile history | Control |
| `raw.macro_series` | `(series_id, observation_date)` | Latest revision; 1,796 rows | No | No | Upsert to latest | No (vintages exist but unused) | DA-04 |
| `raw.macro_series_vintages` | `(series_id, observation_date, vintage_date)` | 105,865 revisions, 2010-01-04..2026-11-06 | No | No | Append-only | Yes for macro | Control |
| `fundamentals.periodic_financials` | `(security_id, period_end, fiscal_period, filed)` | Every filed vintage | No | No | Append per filed vintage | Yes for XBRL vintages | Control (input to DA-07) |
| `model.features` | `(security_id, as_of_date)` | Current computed row; 9,756,631 rows | No | `feature_set_hash`, `feature_version` per row | Upsert replaces values | Only if mutable inputs are complete; they are not (DA-03, DA-05) | DA-12 |
| `model.scores` / `model.rankings` | `(security_id, as_of_date)` | Current score; 464,691 rows, 271 dates | No | No | Upsert on replay (DA-02) | No as-produced history | DA-02, DA-12 |
| `model.predictions` | `(run_id, security_id, as_of_date)` | Every run | `run_id` | `model_version`, `feature_version`, `data_version`, `model_config_hash`, `training_run_id` | Append-only | Yes at prediction level | Control |
| `model.forward_returns` | `(security_id, as_of_date)` | Current 252-day window result | No | No | Upsert (not audited in detail) | Rebuildable only if prices/dividends complete | Related to DA-03/05 |
| `clean.company_profile` | `profile_id` | Snapshot rows with `source_retrieved_at`, `loaded_at` | No | Source provider/time | Append per load; reader picks latest | Partially | — |
| `audit.model_runs` | `run_id` | 18 runs | `run_id` | Model/feature/data versions only | Append-only | Yes, but no policy/generated-at/code/data hash | DA-10 |
| `audit.source_lineage` | `lineage_id` | 26,297 derived rows for 5 fields | No | `model_version`, `feature_set_hash` columns | Delete + reinsert | No past lineage | DA-13 |
| `audit.data_quality` | `(security_id, as_of_date)` | 343,627 rows, 32 dates (2026-10-04..11-09) | No | No | Upsert per date | Yes by date, but only scored dates | — |
| `audit.nightly_runs` | `run_id` | 53 runs (2026-09-24..11-15) | `run_id` | No | Append-only | No: no code/config/env | DA-11 |
| `audit.quarantined_values` | `quarantine_id` | Value, rule, detection, resolution | No | No | Append-only | Yes for quarantined values | Control |
| `data/walk_forward_checkpoint.json` | Path | Latest canonical checkpoint | `run_id` inside | Policy/model/feature/data versions, `generated_at` | Overwritten each run; drift quarantined | One run only | DA-10, DA-18 |
| `artifacts/backtests/metrics_*.json` | Timestamp filename | 7 files (2026-10-26..11-02) | No | No | New files, no manifest | No | DA-09 |
| `artifacts/backtests/daily_*.csv`, `periods_*.csv` | Timestamp filename | Paired with metrics | No | No | New files | No | DA-09 |
| Reports / worksheets | Unknown | Latest-row joins; `CURRENT_DATE` | No | No | No enforced as-of | No as-of view | DA-20 |

## 2. Question-to-Evidence Matrix

| Audit question | Answer today | Evidence | Gap |
|---|---|---|---|
| What score did security X receive on date D? | Yes, current row | `model.scores` | It may be a later replay (DA-02) |
| Was that score produced at D or recomputed later? | No | No `scored_at`/run id | DA-02 |
| Which feature definition produced it? | No | Scores lack hash/version | DA-12 |
| Which feature row values were used? | Indirectly, if not rebuilt since | `model.features` row | Feature row is mutable (DA-12) |
| Which raw evidence did the feature row use? | Partially | Current raw tables | Raw payloads/dividends overwritten (DA-03, DA-05) |
| What did the model know on date D? | Partially | Feature row + filed vintages | No retrieval-time snapshot; SEC payloads latest-only |
| Which model run produced a prediction? | Yes | `model.predictions.run_id`, `training_run_id` | Control |
| Which acceptance policy judged a run? | Only for the one canonical JSON | Checkpoint `contract`; DB omits it | DA-10 |
| Can the headline backtest be regenerated? | No | Latest artifact uses removed `thin_v6`; no manifest | DA-09 |
| Which code version wrote a nightly? | No | `audit.nightly_runs` has no SHA | DA-11 |
| Why was a dividend date dropped? | No | Date overwritten with NULL | DA-05 |
| Why was an amount marked `fmp`/`unresolved`? | Current verdict only | `raw.dividend_amount_check` | No history; no-evidence conflation (DA-06) |
| Which calendar events were known at date D? | No | `CURRENT_DATE` view | DA-15 |
| Which as-of risk-free rate was used? | No | Latest macro revision | DA-04 |
| Which line of lineage recorded a field value? | Current lineage only; 5 fields | `audit.source_lineage` | Rebuilt destructively (DA-13) |
| Why does a security no longer exist? | Archive file, if retained | `data/ticker_conflict_archive/*.json` | Not in DB (DA-14) |

## 3. Artifact and Checkpoint Inventory

### 3.1 Walk-forward checkpoint

`data/walk_forward_checkpoint.json` (generated `2026-10-06T20:19:50Z`, `run_id=d2eccb6c-7e23-48e7-ae28-d92b1dee8e92`, `gate_passed=false`).

| Recorded | Missing |
|---|---|
| `run_id`, `generated_at` | Code SHA, dirty flag |
| `contract.acceptance_policy_version`, model/feature/data versions | Data snapshot hash |
| `gate`, `gate_passed`, `readiness`, `feature_completeness` | Environment/dependency hash |
| Metrics, baseline, embargo, folds, parameters | Input row ids/hashes |
| `n_train_rows`, `n_test_rows`, `n_feature_rows` | Who/what invoked the run |

The database run row contains the versions and gate detail but not the policy version or `generated_at`. If the JSON file is lost or overwritten, the policy generation is no longer recoverable from the warehouse (DA-10, DA-18).

### 3.2 Backtest artifacts

Seven metric files exist, paired with daily and period CSVs. The latest is `metrics_20261102_153616.json`.

| Recorded | Missing |
|---|---|
| 21 summary metrics (return, Sharpe, drawdown, turnover, etc.) | `run_id` |
| `price_filter` string | Code SHA / dirty flag |
| `rejected_prints`, `splits_adjusted`, `unreliable_securities_excluded` | Data version/snapshot |
| `risk_free_applied`, `cash_periods`, `held_periods` | Cost, borrow, execution-lag assumptions |
| Paired daily/period series | Benchmark definition and universe rule set |
| Local timestamp in filename | Config hash, start/end selection |

The latest artifact's `price_filter` (`..._thin_v6`) does not exist in current code (`..._v5`), so the dashboard's "latest complete set" is not a result of the current checkout (DA-09).

### 3.3 Nightly audit

`audit.nightly_runs` records 53 runs with `run_date`, trigger, start/finish, exit code, per-stage status, and row counts. It does not record git SHA, image/requirements hash, CLI arguments, or the warehouse snapshot. A failed or successful nightly cannot be reproduced from the row alone (DA-11).

## 4. Provenance Maturity

| Level | Description | Where it holds |
|---|---|---|
| L0 — none | Value only, no source/time | Most score/report reads |
| L1 — source | Provider, source document, retrieval time | Raw dividend/price rows; `raw.ticker_profile_load` |
| L2 — versioned | Model/feature/data version strings | `model.predictions`; checkpoint JSON |
| L3 — run-addressable | Run id groups writes and is queryable | `model.predictions`; `audit.model_runs` |
| L4 — reconstructable | Immutable inputs plus run manifest plus pinned environment | Nowhere end-to-end |

The system has L2–L3 islands (`model.predictions`, `audit.model_runs`, checkpoint contract) surrounded by L0–L1 stores (`model.scores`, backtest artifacts, nightly audit). The missing piece is a shared run manifest that every writer and artifact carries.

## 5. Minimum Run Manifest (proposal for Stage 2)

A single manifest should be written once per invocation and referenced by every row it writes:

| Field | Purpose | Source |
|---|---|---|
| `run_id` | Group all writes from one invocation | UUID |
| `stage` / `entry_point` | Which command ran | CLI |
| `started_at`, `finished_at` | Time window | Clock (UTC) |
| `code_sha`, `dirty` | Exact code | `git rev-parse HEAD`, `git status --porcelain` |
| `image_digest` or `environment_hash` | Runtime | Docker/`pip freeze` hash |
| `data_snapshot` | Input state | Warehouse marker or table hashes |
| `args` / `config_hash` | Parameters | Parsed CLI/config |
| `as_of` | Resolved evaluation date | Explicit argument |
| `input_row_counts` | What was read | Stage counters |
| `output_row_counts` | What was written | Stage counters |
| `status`, `error` | Outcome | Stage runner |

Rows that should carry `run_id`: scores, rankings, feature writes, labels, predictions, backtest artifacts, checkpoints, and nightly stages. Reports should stamp the manifest they read.

## 6. Limits

- The inventory reflects the live warehouse on 2026-11-15; historical runs are limited to what the current tables retain.
- No external scheduler, object store, or backup catalog was inspected; a copy of an overwritten payload could exist outside this repo.
- `model.forward_returns` was schema-read only; its write path was not audited in this stage.
- Report/worksheet storage was not fully read (BI-37 remains Unknown).
