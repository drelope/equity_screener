# Nightly run verification & data-module audit (single-owner process)

As the single owner of the dividend screener, this is the daily operating
ritual: prove that the 03:00 ET nightly run happened, that every stage exited
cleanly, and that the data modules it wrote still meet the acceptance-quality
floors. Each verification is recorded, so the history of "I checked" is itself
auditable (`audit.nightly_checks`).

## Who / when

- **Owner:** the single owner (the SDLC review's PM/coordinator hat).
- **When:** every morning, once the nightly run has had time to finish —
  target by **09:00 ET** (03:00 ET start, typically done within a couple of
  hours; confirm with the service/journal below).

## The command

```bash
python -m scripts.verify_nightly_run
python -m scripts.verify_nightly_run --json        # machine-readable
python -m scripts.verify_nightly_run --run-date 2026-09-24
```

Exit code: **0 = all checks pass**, **1 = attention needed**. By default the
run date verified is the ET date the last nightly (03:00 ET) would have
covered.

## What it checks ("data-module audit")

| Check | Source | Pass rule (defaults) |
|---|---|---|
| **Nightly run record** | `audit.nightly_runs` | a `success` run (exit 0) exists for the run date |
| **Stages** | `nightly_runs.stages` | no stage recorded `failed` |
| **Freshness (data-module audit)** | newest `raw.ticker_profile` / `raw.companyfacts` / `reference.securities` retrieval and `raw.dividend_data` ex-date | within `--max-age-hours` (default 26 h) |
| **Data quality** | `audit.data_quality` (run date) | mean `quality_score` ≥ 0.50 and ≥ 80% rated good/fair |
| **Dividend accrual coverage** | `raw.dividend_data` × `reference.securities` dividend universe in the lookback window (2025-01-01) | ≥ 95% of the universe covered |
| **Walk-forward gate** | latest `audit.model_runs` | `recall >= MIN_RECALL`; *info* until real labels accrue |

Thresholds are overridable (e.g. `--min-coverage 0.90`). Every run inserts a
verification row into `audit.nightly_checks` (disable with `--no-check-log`,
label ownership with `--verified-by`, annotate with `--notes`).

## Reading the output

```
Nightly verification for 2026-09-23 -> ATTENTION
[ !! ] nightly_run_record: no audit.nightly_runs row
[ OK ] freshness: oldest critical source 25.0h old (SLA 26.0h)
[ !! ] data_quality: mean quality 0.00 (min 0.5), good/fair share 0% (min 80%), n=0
[ !! ] dividend_coverage: 0/4789 dividend securities covered in lookback (0%, min 95%)
[info] walk_forward_gate: no model_runs yet; gate pending real-data accrual
```

Before the first historical data has accrued, `[!!]` on run record / data
quality / coverage is **expected** — it means "the pipeline has not run yet".
The objective is to reach a green morning verification once accrual starts.

## Escalation when something is actually wrong

1. **No nightly run record** — inspect the scheduler and run it once manually:
   - systemd: `systemctl status dividend-etl`, `journalctl -u dividend-etl -n 200`
   - Airflow: DAG run log for `dividend_equity_nightly_etl`
   - then `python -m scripts.run_full_etl` and re-verify.
2. **A stage failed** — the record names it (`nightly_runs.stages`); re-run that
   single module (`python -m scripts.<module>`), checking network/keys first
   (SEC rate-limit, OpenBB provider, `SEC_USER_AGENT`).
3. **Freshness / data-quality floor missed** — data-module symptom: tableau
   ingestion or schema drift. Check `audit.data_quality` for the worst
   securities, then re-run `populate_audit` after the ETL.
4. **Coverage far below 95%** — check the lookback config
   (`DIVIDEND_LOOKBACK_START`) and that stage 2 ran against the full universe
   (not `--limit`/`--tickers`).
5. **After any fix:** re-run `python -m scripts.verify_nightly_run --notes "fixed X"`
   and keep the attention record with a dated note.

## Audit trail

- `audit.nightly_runs` — one row per ETL execution: trigger (`manual` /
  `airflow` / `systemd`), start/finish, exit code, per-stage result. Written
  by `scripts.run_full_etl` (recording failure never fails the ETL; the
  missing record then shows up in verification).
- `audit.nightly_checks` — one row per verification pass: run date, owner,
  status, full findings JSON, notes. This is the dated, auditable proof that
  the Go/No-Go process is actually being performed.

Both tables are installed by `python -m scripts.migrate`
(`sql/migrations/V0005_nightly_run_tracking.sql`; fresh installs get them from
`schema.sql`).

## Monthly review

At each SDLC review cycle, export the two tables and confirm: (a) the nightly
ran ≥ the days in period, (b) every verification is recorded, and (c) any
`attention` row has a follow-up note. This closes the PM/coordinator role's
"ad hoc tracking" gap from the SDLC review — the tracking artifact now exists;
performing the ritual keeps it honest.