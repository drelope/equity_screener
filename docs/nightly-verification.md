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
| **Freshness (data-module audit)** | `MAX(retrieved_at)` in `raw.ticker_profile`, `raw.dividend_data`, `raw.market_data`; `MAX(updated_at)` in `reference.securities`; **`MIN(retrieved_at)`** in `raw.companyfacts` | each source within its own bound in `FRESHNESS_SOURCES` (currently the PoC bounds: **240 h** for the four daily sources, **504 h** for `raw.companyfacts` — see the PoC note below, these are not the deployable values). `--max-age-hours` is the fallback for a source with no bound of its own. Also aged: `raw.sec_submissions` (**MIN**, 504 h), `raw.dividend_calendar` (240 h), `raw.macro_series` (240 h), `raw.macro_series_vintages` and `raw.corporate_actions` (840 h; the nightly splits-calendar loader refreshes the latter's `retrieved_at` every run), `raw.xbrl_frames` (2,400 h); a source with no rows is not aged. Every measurement is also appended to `audit.source_freshness` (latest per source: `audit.source_freshness_latest`), so a source's age over time is a plain query |
| **Data quality** | `audit.data_quality` (run date) | mean `quality_score` ≥ 0.50 and ≥ 80% rated good/fair |
| **Dividend accrual coverage** | `raw.dividend_data` × `reference.securities` dividend universe in the lookback window (2025-01-01) | ≥ 95% of the universe covered |
| **Walk-forward verdict** | latest `audit.model_runs` | *info*: while the verdict is `no_go` (accepted 2026-10-06; rule-based scoring is in use) it never alarms and never reads as a pass. A `go` row is checked against `recall >= MIN_RECALL` |
| **Ticker conflicts** | open `TICKER_CIK_CONFLICT` rows in `audit.quarantined_values` | none open (see below) |

Thresholds are overridable (e.g. `--min-coverage 0.90`). Every run inserts a
verification row into `audit.nightly_checks` (disable with `--no-check-log`,
label ownership with `--verified-by`, annotate with `--notes`).

### Post-nightly OpenBB dividend amount guard

The one-time post-nightly check (`python -m scripts.post_nightly_check --run-date <date>`)
also fails on any OPENBB per-share amount above `$1,000,000` that is not already parked in
`audit.quarantined_values` with rule `OPENBB_DIVIDEND_AMOUNT_ABSURD`. Known rows are allowed
because the raw values stay as evidence; a new unquarantined amount means the ingestion
ceiling did not apply. The result appears in the post-nightly markdown report
(`artifacts/post_nightly/latest.md`). A blanket `$1,000` OpenBB cap is deliberately not used: valid pre-split payments can be tens of thousands of
dollars per unadjusted share (L012).

### Preferred security consistency

Missing coupons/preferences, repeated titles and issuer-only titles are
informational data gaps, not permission to guess a rate or assign $25 to every
preferred. The $1,000/share preference threshold is a review trigger, not a cap:
an underlying preferred share and its listed depositary receipt have different
units.

The nightly runs `populate_sec_instrument_titles --preferred-only` after the
reference stage and before dividend profiles and the contract miner. It refreshes
changed filings and retries issuers whose active preferred symbols lack titles.
Filed symbol variants (for example `FRT-C` vs `FRT-PC`, or `STT.PRG` vs `STT-PG`)
are bound only to a unique known symbol of the same issuer. Exact CIK/ticker
titles replace display names and fill missing title-parsed terms; existing terms
are preserved. Depositary amounts are left to the narrative contract miner,
which applies the depositary ratio from the newly acquired title.
Clean ticker/company profiles are rebuilt after repairs and contract mining,
so the nightly does not leave them one run behind the final reference terms.
If all raw profiles lack a preference, the clean profile uses the representative
security's mined contract value and retains its source document ID in lineage.
Conflicting raw profile preferences still remain NULL and flagged.
The XML parser pairs a trading symbol with its title by dimensional context,
not merely by period or document position. This preserves identical depositary
titles reported for several classes and ignores unpaired rights titles; older
periods cannot overwrite a symbol's newer title.

Exact CIK/ticker cover titles outrank symbol heuristics: for example, a `-PE`
symbol can be a subordinated debenture, not a preferred share. The classification
repair applies those corrections without changing security IDs and retains the
source filing in the evidence. Filed aliases are matched against canonical
reference symbols, not against another spelling from submissions; `/PR`, `.PR.`
and space-separated `PR` spellings are supported.

For an evidence-backed backfill, run
`python -m scripts.populate_sec_instrument_titles --preferred-only`, then
`python -m scripts.populate_contract_terms` and rebuild the clean ticker profiles.
Do not overlap a manual backfill with a nightly. `--skip-instrument-titles` is
available for partial/debug pipeline runs. Unsupported terms remain NULL.

The walk-forward NO-GO detail lists the failed acceptance checks and their
measured/required values from `audit.model_runs.gate_detail`. This is not a
request to bypass the gate: a model that fails minority-class recall or
balanced-accuracy lift remains unadopted, and rule-based scoring stays in use.

## Reading the output

```
Nightly verification for 2026-09-23 -> ATTENTION
[ !! ] nightly_run_record: no audit.nightly_runs row
[ OK ] freshness: raw.ticker_profile 4.0h (SLA 240.0h); raw.dividend_data 21.6h (SLA 240.0h);
     raw.market_data 22.4h (SLA 240.0h); reference.securities 4.0h (SLA 240.0h);
     raw.companyfacts 71.6h (SLA 504.0h)
[ !! ] data_quality: mean quality 0.00 (min 0.5), good/fair share 0% (min 80%), n=0
[ !! ] dividend_coverage: 0/4789 dividend securities covered in lookback (0%, min 95%)
[info] walk_forward_gate: no model_runs yet; gate pending real-data accrual
```

The freshness line names every source and its own bound, so a breach is
attributable rather than an anonymous worst-case number. A source with no stored
rows is not aged — an unmeasured source must not read as a stale one.

`raw.companyfacts` holds one immutable snapshot of each issuer's entire SEC
history and is refreshed on a weekly cycle
(`run_full_etl --companyfacts-refresh-after-days`, default 5; `--refresh` forces a
re-fetch now). Its bound is matched to that cadence rather than chosen to make the
current data pass — 8 days once the bounds are reverted (below), 21 days as the
current PoC value: a nightly that stops running still ages it out either way.

It is also the one source aged by `MIN` rather than `MAX`, because a refresh run
rewrites every due row: its age is the age of the **stalest payload still
carried**, and reading `MAX` would let a partial refresh pass — re-fetching 2 of
7,066 CIKs moves `MAX` to now and reports the source as fresh while 7,064
snapshots are a week old. The other four sources re-fetch a moving lookback
window and their out-of-window rows are never meant to be touched, so `MAX` is
the only meaningful reading for those.

Because of that, all three `raw.companyfacts` populations need a refresh cadence or
one stale CIK fails the whole source. The nightly covers them in priority order:
stage 4a (preferred set, 3 days) → 4b (dividend universe, 5 days) → 4c (CIKs in
neither universe, 5 days). A `raw.companyfacts` breach therefore means *one CIK was
not refreshed*, not that the table is stale — the detail line reports the age, and
the per-CIK accounting (`refreshed` / `skipped` / `deferred`) is in the stage log.

Note the margin. The age at check time is `cadence + days missed`, so the
tolerance is `bound - cadence`, not the cadence itself. At 5 days against the
reverted 8-day bound that is **3 consecutive missed nightlies** (against the
current 21-day PoC bound it is 16); stage 4a at 3 days tolerates 5 of the
reverted bound. The earlier 7-day default tolerated only 1 — one laptop lid
closed at 03:00 was a breach — which is why it is 5. A test pins the
relationship so the two constants cannot drift apart silently.

**These bounds are currently PoC bounds and must be reverted before deployment.**
`FRESHNESS_SOURCES` holds `POC_DAILY_BOUND_HOURS` (240h) and
`POC_COMPANYFACTS_BOUND_HOURS` (504h), widened during the proof of concept so the
check does not report a breach every morning the development host is not running
at 03:00. The four daily sources were previously bounded at 26h, which on a daily
cadence is 2 hours of tolerance — less than one missed nightly. See
`REVERT_BEFORE_DEPLOY` in `docs/data-health-workstreams.md` for the real values to
restore and the reasoning. A test asserts every bound is looser than the cadence it
covers, so a healthy nightly cannot breach its own check.

`n=0` on data quality does **not** mean the pipeline has never run.
`populate_audit` is stage 9: `run_full_etl` skips every stage after the first
failure, so the newest `audit.data_quality` date stays wherever the last run
that reached stage 9 left it (currently 2026-10-04). Read
`nightly_runs.stages` first — `[!!]` on run record or stages names the real
cause, and the data-quality/coverage lines are then downstream symptoms.
Before any historical data has accrued at all, `[!!]` on run record / data
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
   (`DIVIDEND_LOOKBACK_START`) and that stage 3 ran against the full universe
   (not `--limit`/`--tickers`).
5. **After any fix:** re-run `python -m scripts.verify_nightly_run --notes "fixed X"`
   and keep the attention record with a dated note.

### A ticker/CIK conflict is a warning, not a failure

`populate_raw_tables` skips a ticker that the SEC snapshot now assigns to a
different CIK than the one a `reference.securities` row still references, and
finishes with exit 0. It never overwrites or re-keys the existing mapping, and the
stage is still recorded as `ok`. The stage writes each skipped conflict to
`audit.quarantined_values` (`table_schema = 'raw'`, `rule = TICKER_CIK_CONFLICT`, the
ticker as `row_key`, the incoming CIK as `observed_value`), and `verify_nightly_run`
reports any open row as **attention** (`ticker_conflicts`). A conflict SEC stops
reporting is resolved automatically on the next full run; one an operator released
is reopened if it returns. A `--limit` run or the offline re-read never resolves
anything, because it sees only part of the file. The journal still has the detail:

```
journalctl -u dividend-etl | grep -E "ticker_cik_conflict|completed with warnings"
```

Each conflict is one JSON line (`conflict_type: TICKER_CIK_CONFLICT`, both CIKs and
issuer names, `resolution: MANUAL_REVIEW_REQUIRED`). The skipped ticker stays out of
`raw.company_ticker` and so out of `reference.securities` until someone decides who
owns it. A run in which *every* ticker conflicts writes nothing and still fails.

#### Resolving a conflict

The decision and the remedy are two commands in `scripts.resolve_ticker_conflict`.

```
python -m scripts.resolve_ticker_conflict review --ticker PORT-UN
```

`review` is read-only. It re-derives the conflict exactly as the stage does and asks
SEC's own per-issuer submissions (live, falling back to the stored copy) which issuer
lists the ticker:

| Result | Meaning | Action |
|---|---|---|
| `STALE` | SEC lists the ticker under the incoming CIK and no longer under the existing one | release it |
| `INCOMING_WRONG` | SEC still lists it under the existing CIK and not the incoming one | leave it; `release` refuses |
| `AMBIGUOUS` | both list it, neither does, or an issuer's submissions are unavailable or list no tickers (SEC leaves the list empty for a brand-new registrant, so empty means unknown, not absent) | leave it, or verify externally and release with `--basis` |

Newer is not the test. Only SEC moving the ticker counts, and every doubt resolves to
`AMBIGUOUS`, which changes nothing and keeps reporting a warning nightly.

**Why "release" removes the row instead of deactivating it.** Deactivating or
re-keying cannot free a ticker. `populate_securities` sets `active = TRUE` for every
`raw.company_ticker` row on every run, and `fk_securities_company_ticker` keeps
referencing a row whether it is active or not, so an inactive row still blocks
`raw.company_ticker` from changing the CIK. The key is `(ticker, cik)` and
`company_ticker` holds one CIK per ticker, so there is no re-key. Removal is the only
thing that releases the ticker, which is why it is gated.

```
python -m scripts.resolve_ticker_conflict release --ticker PORT-UN --reviewed-by <you>
python -m scripts.resolve_ticker_conflict release --ticker PORT-UN --reviewed-by <you> \
    --execute --confirm PORT-UN [--basis "<evidence>"]
```

The first form is a dry run and prints what would be deleted per table. `--execute`
needs `--confirm` to repeat the ticker, takes the pipeline lock (so it cannot overlap a
nightly), and in one transaction:

1. writes every row it will delete to `data/ticker_conflict_archive/<ticker>_<cik>_<utc>.json`
   and flushes it to disk, before any delete (`data/` is git-ignored, so this archive is
   local; copy it somewhere durable if the history matters);
2. deletes children before parents, using the foreign-key graph read from the live
   catalog rather than a hand-kept table list, and aborts if any delete count differs
   from the plan;
3. aborts if the stale mapping is still referenced afterwards;
4. records the release in `audit.quarantined_values` (`rule = TICKER_CIK_CONFLICT`,
   `resolved_at` set, reviewer, classification, basis and archive name in
   `resolution_note`).

It does not touch `raw.company_ticker`. The next ordinary `populate_raw_tables` run
finds the ticker unreferenced and ingests the incoming CIK with no override. Only the
ticker in question is removed: other tickers of the same issuer (for `PORT-UN`, `ANGX`)
are untouched. Restoring from the archive is manual; the file holds each row as JSON.

After refreshing the raw snapshot, rebuild only the released instruments rather
than reclassifying the entire universe:

```
python -m scripts.populate_reference_tables --securities --tickers XRPN,XRPNW
python -m scripts.verify_nightly_run --notes "Released reviewed predecessor mappings and ingested successors"
```

For the October 2026 XRPN/XRPNW succession, Evernorth's
[closing 8-K](https://www.sec.gov/Archives/edgar/data/2092592/000119312526419146/d24481d8k.htm)
documents the October 9 closing, suspension/delisting of Armada's predecessor
instruments, and October 12 start of trading for Evernorth's common stock and
warrants under those same symbols. This is external evidence for an
`AMBIGUOUS` review when the successor submissions ticker array is still empty;
do not treat the empty array alone as evidence or release sibling symbols.

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

## Replaying a historical date (scoring-policy change)

The nightly scores the newest feature date only. A change to the scoring policy
-- a weight, the coverage floor, a feature definition -- makes every already
published date an output of a rule that no longer holds, so the change has to be
replayed over history rather than waited out one night at a time.

```bash
python -m scripts.score_rank --as-of 2026-09-29
```

`--as-of` anchors the feature window on that date instead of the newest row;
`model.scores` and `model.rankings` are rewritten at it, and `model.predictions`
gets a fresh run. The dates can be replayed in any order.

**A replay prunes superseded predictions by default.** `model.scores` and
`model.rankings` are keyed by `(security_id, as_of_date)` and every run prunes
the securities it did not write at that date; a replay can shrink the frame, so
the superseded `model.predictions` runs -- which still cover the old, larger
frame -- would otherwise survive. `model.current_predictions` resolves to the
newest run *per security*, so it would then report the union of the old and new
frames while `model.scores` held only the new, and the two would quietly
disagree on the date's coverage. Pass `--keep-superseded` only if those rows are
genuinely wanted. The nightly keeps its opt-in retention (`run_full_etl` passes
`--prune-superseded`), because its frame is stable and the superseded runs are
the audit trail.

**A replay refuses the wrong date.** If the requested date is not the newest
feature row within the carry-forward window (a weekend or holiday, or a date past
the newest feature), the run exits **2** with "refusing to re-score the wrong
date" rather than write the wrong day's scores. A missing or malformed `--as-of`
is likewise a usage error, never a silent fall back to the nightly date.

After a replay, confirm the coverage agreement the prune protects:

```sql
SELECT count(*) FROM (
  SELECT v.as_of_date
  FROM (SELECT as_of_date, count(*) n FROM model.current_predictions GROUP BY 1) v
  JOIN (SELECT as_of_date, count(*) n FROM model.scores GROUP BY 1) s USING (as_of_date)
  WHERE v.n <> s.n) x;
```

Zero rows means `current_predictions` and `scores` agree on every date.

## Monthly review

At each SDLC review cycle, export the two tables and confirm: (a) the nightly
ran ≥ the days in period, (b) every verification is recorded, and (c) any
`attention` row has a follow-up note. This closes the PM/coordinator role's
"ad hoc tracking" gap from the SDLC review — the tracking artifact now exists;
performing the ritual keeps it honest.