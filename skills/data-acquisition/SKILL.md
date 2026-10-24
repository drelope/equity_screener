---
name: data-acquisition
description: "Use when fetching or refreshing SEC, OpenBB, FMP or FRED data, adding a provider, or backfilling the dividend universe. Do not use for profiling sources, derived tables, or repairing classification."
version: 1
risk: heavy
owner: data-engineering
entrypoint: none  # none|fixed|list
tags: []
---

# Data Acquisition

Fetch source data and upsert it into `raw.*` with provenance. Acquisition is
idempotent: a re-run refreshes the same rows rather than duplicating them.

## When to use / when not to use

Use when:

- running a source stage for the nightly or a ticker subset;
- backfilling dividends, prices, filings or macro inputs;
- adding or rotating a provider;
- investigating an empty or stale `raw.*` table.

Do not use when:

- the question is whether the data is good (`data-understanding`);
- the task is deriving features or clean profiles (`data-transformation`);
- the task is classification repair (`data-transformation`);
- the task is the full ordered nightly (`data-refresh-operations`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Env | `SEC_USER_AGENT` | yes for SEC | Real contact string; a placeholder fails fast. |
| Env | `OPENBB_PROVIDER` | conditional | Empty falls back to keyless providers. |
| File | `ObbCredentials.json` | conditional | Gitignored provider keys; never read aloud. |
| Doc | `docs/data-acquisition.md` | yes | Lookback and backfill rules. |
| Doc | `README.md` (Data Workflow) | yes | Stage order and flags. |
| Table | `reference.securities` | yes | `dividend = TRUE` gates stages 2-5. |

## Procedure

1. Run the preflight from `SYSTEM.md`. Confirm `python -m scripts.migrate --check`
   exits 0 and the SEC user agent is real before any SEC stage.
2. For a full ordered acquisition, use `python -m scripts.run_full_etl`; for a
   single source, run its stage script from the README "Data Workflow":
   - `python -m scripts.populate_raw_tables`
   - `python -m scripts.populate_reference_tables`
   - `python -m scripts.populate_sec_instrument_titles --preferred-only`
   - `python -m scripts.populate_exchange_listing_titles`
   - `python -m scripts.populate_market_data`
   - `python -m scripts.populate_dividend_data`
   - `python -m scripts.populate_companyfacts`
   - `python -m scripts.populate_sec_documents`
   - `python -m scripts.populate_fmp_fundamentals`
   - `python -m scripts.populate_macro_inputs`
3. Scope test runs with `--limit`, `--tickers` or `--sources`. Never combine a
   partial run with `--run-labels`.
4. Respect the lookback rules: dividends default to
   `DIVIDEND_LOOKBACK_START` and accrue forward; total history is the explicit
   `--dividend-full-history` / `--full-history` provision.
5. Do not lower the dividend-recency window or disable
   `ENFORCE_DIVIDEND_RECENCY` to make a ticker appear; that changes the
   universe.
6. Confirm the upsert counts and provenance in the stage output, then run the
   relevant population tests.

## Outputs

- `raw.company_ticker`, `raw.ticker_profile`, `raw.company_classification`;
- `raw.market_data`, `raw.dividend_data`;
- `raw.sec_submissions`, `raw.companyfacts`, `raw.sec_documents`;
- `raw.fmp_statements`, `raw.fmp_dcf`, `raw.fmp_filings`;
- `raw.macro_series`, `raw.macro_etf_sectors`;
- one `audit.nightly_runs` row when run through `run_full_etl`.

## Verification

Pass when:

- the stage exits 0 and reports the expected upserted/updated counts;
- the matching test module passes, for example:

  ```bash
  python -m pytest -q tests/test_populate_companyfacts.py tests/test_populate_dividend_data.py
  ```

- the new rows exist for the requested tickers and carry `provider`,
  `content_hash` and `raw_payload` where the table defines them;
- no non-dividend security was requested for SEC/OpenBB stages.

## Failure handling

- Placeholder `SEC_USER_AGENT`: stop; no SEC request may run.
- Missing provider key: report the source and let the stage skip cleanly; do
  not fabricate a key or a value.
- SEC rate limit or transient HTTP error: the client retries; if it still
  fails, stop and report. Do not loop or disable backoff.
- Stored payload is within the companyfacts refresh window: that is expected
  skipping, not a failure.
- A source disagrees with another: retain both with provenance and route to
  `data-understanding`; do not overwrite one arbitrarily.
- Partial run requested: report its scope and never label it.

## Source of truth

- `docs/data-acquisition.md`
- `scripts/populate_*.py`
- `src/crispdm/sec_client.py`
- `src/crispdm/openbb_client.py`
- `src/crispdm/config.py`
- `README.md` (Data Workflow)

## Runner

- **Mode:** Follow this skill's procedure. The deterministic runner only executes allowlisted fixed entrypoints; most work here is manual unless stated otherwise.
- **Confirmation:** Skills with `risk: write` or `risk: heavy` require `--yes` when executed via the runner. Never parse commands from Markdown.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches the database or schema.
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No pipeline lock held / no conflicting run in progress if executing `run_full_etl`.
- [ ] Scope narrowed to the smallest change that satisfies the request.

## Handoffs

- **DB/schema drift:** route to `data-storage-schema` with `migrate --check` output and affected tables.
- **Missing/dirty source data:** route to `data-acquisition` with coverage gaps and tables.
- **Freshness/health check:** route to `observability-nightly-verification` with `audit.nightly_runs`/`audit.nightly_checks`.
- **Security/secret risk:** route to `security-compliance` (do not share secret values).
- **Investment validation, KPI/risk interpretation or a report:** route to `financial-analysis`.
- **Scoring/labeling policy:** route to `financial-scoring` or `modeling-evaluation` per boundaries above.

## Stop conditions

- [ ] Task is outside this skill's scope (see "Do not use when").
- [ ] `python -m scripts.migrate --check` reports pending migrations before a write operation.
- [ ] `--run-labels` requested with `--limit` or `--tickers` (partial runs must not be labeled).
- [ ] Action would delete reference rows, prune historical features/returns outside the allowed command, or release a ticker conflict without its dedicated confirmed command.
- [ ] Secret would be printed, logged, or committed.
- [ ] Non-zero exit from a required command with no documented "finding" handling.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** affected tables/rows, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger state, or files written.
- **Findings:** relation/filter/as-of for quantitative claims; diffs for schema/config changes.
- **Handoffs:** target skill + reason + evidence attached.
