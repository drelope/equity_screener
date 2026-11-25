# Stage 1D Determinism Inventory

| Field | Value |
|---|---|
| Stage | 1D — Determinism and auditability |
| Scope | Clock inputs, ordering/tie-breaks, mutable state, runtime pins |
| Method | Code read plus SELECT-only warehouse probes; no writes or re-runs |
| Repo HEAD | `d748cea` |
| Date | 2026-11-15 |

A process is **replay-deterministic** when the same source snapshot, explicit `as_of`, and pinned environment produce the same rows. It is **audit-reproducible** when it also records which code, data, config, and environment were used. This inventory separates the two.

## 1. Clock Inputs

| Component | Default | Explicit control | What changes with the clock | Finding |
|---|---|---|---|---|
| `identity.resolve_security_ids` | `as_of or date.today()` | `as_of` argument | Ticker/CIK resolution window and active-identity choice | DA-01 |
| `sec_client.classify_companyfacts` | `as_of or date.today()` | `as_of`, `lookback_days` | Dividend recency floor and paid-dividend ceiling | DA-01 |
| `dividend_universe.observed_payer_keys` | `today or date.today()` | `today` argument | Which positive payments enter the payer universe | DA-01 |
| `frames.default_periods` | `today or date.today()` | `today`, `years` | Annual/instant period codes requested from a provider | DA-01 |
| `macro_inputs.collect_rows` | `date.today()` | `lookback_days` only | Start/end of the macro fetch window | DA-01 |
| `label_targets --cutoff` | `default=date.today()` | `--cutoff` | Which feature rows become eligible for a label | DA-01, DA-16 |
| `build_historical_universe --end-year` | `default=date.today().year` | `--end-year` | Historical EDGAR year range | DA-01 |
| `load_dividend_calendar` | `today = date.today()` | `--back`, `--ahead` only | Calendar fetch window and `upcoming` membership | DA-01, DA-15 |
| `analysis_autofill` | `pd.Timestamp.now()` | None enforced | Default worksheet date and latest-row joins | DA-01, DA-20 |
| API/report `CURRENT_DATE` | Database clock | None | Which fundamentals and calendar rows a report sees | DA-20 |
| `audit.nightly_runs.run_date` | `date.today()` | None; no CLI argument | Nightly grouping and alignment with the stage timestamps | DA-11 |

**Verdict:** every replay-visible function accepts an explicit date, so deterministic operation is *possible*. Determinism is not *enforced*: the default for the model, label, universe, and calendar paths is the wall clock. The suite does not freeze the clock or run a fixed `as_of` on two dates (DA-19).

## 2. Replay Matrix

| Path | Explicit `as_of` available | Default deterministic | Persists the resolved date | Verdict |
|---|---|---|---|---|
| Identity resolution | Yes | No | In the output row only | Replayable only when caller pins `as_of` |
| SEC dividend classification | Yes | No | In `reference.securities` fields | Replayable only when caller pins `as_of` |
| Feature build | Yes (`--as-of`, date range) | Yes for an explicit range | Yes, `as_of_date` on each row | Replayable, but inputs are mutable (DA-03, DA-05) |
| Labels | Yes (`--cutoff`) | No | No label run/cutoff stored (DA-16) | Not audit-reproducible |
| Scoring | Yes (`--as-of`) | Yes for an explicit date | No run/cutoff; row mutable (DA-02) | Replayable as a computation, not as produced |
| Walk-forward | Yes (date frame) | Yes for a fixed frame | Checkpoint `generated_at`; run id in DB | Replayable; no code/data hash (DA-10) |
| Backtest | Yes (warehouse score dates) | Yes for a fixed warehouse | No manifest (DA-09) | Not audit-reproducible |
| Macro inputs | Yes (fetch window only) | No | Observation dates, no fetch window | Replayable only from completed vintages |
| Dividend calendar | No (load window only) | No | Event rows, no snapshot id | Not replayable as-of (DA-15) |
| Reports/autofill | No | No | No enforced as-of (DA-20) | Not replayable |

## 3. Ordering and Tie-Breaks

| Location | Current ordering | Risk | Finding |
|---|---|---|---|
| `features.py` quarterly `DISTINCT ON` | `security_id`, `period_end`, `GREATEST(filed, period_end)`, then `(eps IS NULL)`, `fiscal_period` | Ties on the first three fields can pick an arbitrary row | DA-07 |
| `features.py` FY `DISTINCT ON` | `security_id`, `observation_date`, then `period_end DESC` | Each vintage interval is bounded by `filed`/`filed_next`, so the pick is usually unique; no explicit `filed` tie-break | DA-07 (related) |
| `portfolio.UNIVERSE_SQL` price LATERAL | No `ORDER BY`, `LIMIT 1` | Arbitrary price if a security/date has more than one provider row | DA-08 |
| `portfolio.total_return_matrix` | `drop_duplicates(..., keep="last")`, then `ffill` | Duplicate keys resolve by input order | DA-08 |
| `features` and `returns` price joins | No provider predicate | Multi-provider rows multiply or mix joins | DA-08 |
| `macro_vintages.as_of_series` | `ORDER BY observation_date, vintage_date DESC` | Deterministic if `(series_id, observation_date, vintage_date)` is unique | Control (no finding) |
| `model.walk_forward` / `walk_forward_folds` | Sorts labels before cutting | Correct; no regression test | DA-19 (test gap) |
| `backtest.run_walk_forward` periods | Disjoint by construction, cash starts after formation | Correct; no regression test | DA-19 (test gap) |

**Verdict:** the observed single-provider warehouse hides the price hazards. The quarterly fundamentals tie-break is a live arbitrary pick. The walk-forward/backtest controls are correct in code but unprotected.

## 4. Mutable State

| Store | Key | Write behaviour | History retained | Finding |
|---|---|---|---|---|
| `raw.companyfacts` | `cik` | Upsert; payload replaced when hash changes | No | DA-03 |
| `raw.sec_submissions` | `cik` | Upsert; payload replaced when hash changes | No | DA-03 |
| `raw.macro_series` | `(series_id, observation_date)` | Upsert to latest revision | No (vintages table separate) | DA-04 |
| `raw.dividend_data` | `(security_id, ex_date, provider)` | Upsert; dates and amounts replaced | No | DA-05 |
| `raw.dividend_amount_check` | `(ticker, ex_date)` | Upsert; verdict and `checked_at` replaced | No | DA-06 |
| `raw.dividend_calendar` | Calendar event key | Upsert; no delete/withdrawal | Current rows only | DA-15 |
| `model.features` | `(security_id, as_of_date)` | Upsert; values, hash, version replaced | No | DA-12 |
| `model.scores` / `model.rankings` | `(security_id, as_of_date)` | Upsert on replay | No | DA-02 |
| `model.predictions` | `(run_id, security_id, as_of_date)` | Append-only per run | Yes | Control |
| `audit.model_runs` | `run_id` | Append-only per run | Yes, but incomplete columns | DA-10 |
| `audit.nightly_runs` | `run_id` (bigserial) | Append-only per nightly | Yes, but no code/env stamp | DA-11 |
| `audit.source_lineage` | `lineage_id` | Delete + reinsert derived fields | No | DA-13 |
| `raw.ticker_profile_load` | `load_id` | Append-only | Yes | Control |
| `raw.macro_series_vintages` | `(series_id, observation_date, vintage_date)` | Append-only | Yes | Control |
| `audit.quarantined_values` | `quarantine_id` | Append-only; resolved by timestamp | Yes | Control |
| `data/walk_forward_checkpoint.json` | Path | Overwritten each run; quarantined only on drift/failure | One canonical file | DA-18 |
| `artifacts/backtests/*` | Timestamped filename | New files, no manifest | Files only, no identity | DA-09 |

## 5. Runtime and Environment

| Item | State on 2026-11-15 | Finding |
|---|---|---|
| HEAD dependency list | 20 direct pins in `requirements.txt` | Baseline |
| Working tree `requirements.txt` | Modified to a 238-line unpinned freeze, 0 `==` | DA-17 |
| Lockfile | None (`uv.lock`, `poetry.lock`, `Pipfile.lock` absent) | DA-17 |
| Installed pytest | 9.1.1; dev pin 8.4.2 | DA-17 |
| Installed streamlit | 1.67.0; HEAD pin 1.64.0 | DA-17 |
| Installed pandas/numpy/scikit-learn | 2.3.3 / 2.2.6 / 1.7.2 (match HEAD pins) | — |
| Installed openbb | Missing (import absent) | DA-17 |
| Docker install | `pip install -r requirements.txt` from the worktree | DA-17 |
| CI test command | Bare `pytest -q`; no lock, no coverage gate | DA-17, DA-19 |

## 6. Determinism Controls Present

| Control | Location | Status |
|---|---|---|
| Point-in-time feature window excludes future observations | `feature_window.py` | Present; no as-of membership test (TG-04) |
| Label window fully elapsed before cutoff | `label_targets.label_value` | Present; cutoff defaults to today (DA-01) |
| Walk-forward sorts before cutting | `model.py:464,492` | Present; untested (DA-19) |
| Embargo between train and test | `model.walk_forward` | Present; tested |
| Fold verdict fails closed on skipped folds | `evaluate_walk_forward` | Present; tested |
| Checkpoint contract drift detection | `evaluate_walk_forward.contract_drift` | Present; tested |
| Feature hash/version per row | `model.features` | Present; not propagated to scores (DA-12) |
| Prediction run id and versions | `model.predictions` | Present; not used by backtest |
| Quarantine append-only | `audit.quarantined_values` | Present |
| Provider list currently single | `raw.market_data` | Accidental, not enforced (DA-08) |

## 7. Verification Queries Used

These were SELECT-only and are reproducible on the current warehouse:

```sql
SELECT count(*), count(DISTINCT security_id), count(DISTINCT as_of_date) FROM model.scores;
SELECT min(as_of_date), max(as_of_date), count(*) FROM model.scores;
SELECT count(*), min(as_of_date), max(as_of_date) FROM model.features;
SELECT provider, count(*), min(ex_dividend_date), max(ex_dividend_date) FROM raw.dividend_data GROUP BY provider;
SELECT chosen, count(*) FROM raw.dividend_amount_check GROUP BY chosen;
SELECT count(*), count(DISTINCT as_of_date), min(as_of_date), max(as_of_date) FROM audit.data_quality;
SELECT count(*), min(run_date), max(run_date) FROM audit.nightly_runs;
SELECT field_name, count(*) FROM audit.source_lineage GROUP BY field_name;
SELECT count(*) FROM raw.macro_series;
SELECT count(*) FROM raw.companyfacts;
SELECT count(*) FROM raw.sec_submissions;
SELECT count(*) FROM raw.ticker_profile_load;
SELECT count(*) FROM raw.dividend_calendar;
SELECT count(*) FROM raw.upcoming_dividends;
SELECT count(DISTINCT run_id) FROM model.predictions;
```

No `INSERT`, `UPDATE`, `DELETE`, DDL, or pipeline invocation was issued in this stage.
