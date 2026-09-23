# Data acquisition: dividend lookback, nightly accrual, and total-history backfill

This is the *how-to-acquire* companion to
[model-labeling-plan.md](model-labeling-plan.md): it explains the provisions so
a **passing labeled walk-forward run** (the Azure Go/No-Go) can be demonstrated
once 12 months of dividend data to 2025-01-01 has been acquired and continues
to accrue.

## The three provisions

| Provision | When | Command |
|---|---|---|
| **12-month lookback backfill** | Now — first run, acquires dividend history from `2025-01-01` to today | `python -m scripts.run_full_etl` (stage 2 defaults to `DIVIDEND_LOOKBACK_START`) |
| **Nightly accrual** | Ongoing — re-runs the ETL daily at 03:00 so the same window stays current and grows forward | Airflow `airflow/dags/dividend_etl_dag.py` or systemd `ops/systemd/dividend-etl.{service,timer}` |
| **Total-history backfill** | One-time, *after* the PoC gate passes — fetches the full available dividend history per security | `python -m scripts.run_full_etl --dividend-full-history` |

All three rely on the same upsert into `raw.dividend_data`
(`ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE`), so
re-running any of them is idempotent and safe.

## 1. The 12-month lookback (initial backfill)

`populate_dividend_data` (ETL stage 2) acquires dividend events from:

- **OpenBB** — bounded by its start date, which defaults to
  `settings.dividend_lookback_start` (`DIVIDEND_LOOKBACK_START`, default
  `2025-01-01`). This is the lookback that guarantees a full 12-month window is
  present once the pipeline runs.
- **SEC XBRL** (`raw.companyfacts` / live companyfacts JSON) — always returns
  the complete posted history regardless of the start bound.

So the very first `run_full_etl` acquires dividends covering `2025-01-01` →
today from OpenBB **and** the full SEC XBRL history, merged, deduplicated, and
written to `raw.dividend_data`.

## 2. Nightly accrual (continues into the future)

The scheduler runs the full ETL once daily at 03:00 (Airflow DAG or the
systemd timer). Because stage 2 keeps its lookback start fixed at
`2025-01-01` while its end defaults to *now*, each nightly run:

- does not lose the backfill window, and
- appends/refreshes every dividend event that accrued since the previous run.

`build_features` (`scripts.build_features`) then snapshots features at every
market-data observation date, and — once a feature row's 365-day outcome window
has fully elapsed before the label cutoff — `scripts.label_targets` (ETL stage
7, `run_full_etl --run-labels`) emits its label. Labels start appearing once
`as_of_date <= today - 365 days`, i.e. for as-of dates on/after the lookback
start (`2025-01-01`) roughly one year after the first acquisition.

## 3. Total historical dividend data (post-PoC provision)

Once the proof of concept has passed (a labeled walk-forward run meeting
`MIN_RECALL`, recorded in `audit.model_runs`), switch the ETL and scheduler to
total history exactly once:

```bash
python -m scripts.run_full_etl --dividend-full-history
```

This passes `--full-history` to stage 2, which asks OpenBB for the full
available history (from `1970-01-01`) instead of the 12-month lookback; the SEC
XBRL source already returns full history, so together this is the complete
dividend record per security. Keep the flag on the scheduler (Airflow DAG /
systemd `ExecStart`) afterwards so nightly runs keep refreshing the entire
history.

> Why not run full history before the PoC? The lookback keeps the first
> acquisition small (one year of events, fast, low API volume). Total history is
> a larger one-time pull, so it is deliberately gated on the gate passing.

## 4. From data to a passing labeled walk-forward run

Once labeled rows exist (`model.features.target_sustainable_dividend` not
null), record the checkpoint:

```bash
python -m scripts.label_targets                 # (or already run by run_full_etl --run-labels)
python -m scripts.evaluate_walk_forward
```

- `recall >= MIN_RECALL` → writes `data/walk_forward_checkpoint.json` with
  `gate_passed: true` and inserts the run into `audit.model_runs` (exit 0).
- fewer than 10 labeled rows → informational exit 0, no checkpoint yet.

### Demonstrate the mechanism immediately (no data required)

```bash
python -m scripts.dry_run_walk_forward
```

Runs the identical walk-forward gate on an in-memory synthetic labeled sample
(no DB/network writes) and writes a dry-run checkpoint to `/tmp`. It proves the
Go/No-Go path end-to-end today; the real-data path above replaces the sample.

## 5. Tuning

- Change the lookback from 12 months: set `DIVIDEND_LOOKBACK_START=YYYY-MM-DD`
  in `.env` (or the default in `src/crispdm/config.py`).
- Scope acquisition during testing: `--tickers KO,VZ,PG` or `--limit N` on
  stage 2 (never combined with `--run-labels`, which is refused on partial runs
  to keep labels immutable).