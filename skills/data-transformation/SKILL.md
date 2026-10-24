---
name: data-transformation
description: "Use when building clean profiles, fundamentals, features, forward returns or mined contract terms from stored payloads, or running the classification repairs. Do not use for source acquisition, schema changes, or score weights."
version: 1
risk: write
owner: data-engineering
entrypoint: none  # none|fixed|list
tags: []
---

# Data Transformation

Turn stored raw payloads into the clean, fundamental and feature tables the
scoring layer reads. Transformations are offline: no network calls.

## When to use / when not to use

Use when:

- rebuilding `clean.*` profiles or corporate actions;
- building `fundamentals.periodic_financials`;
- rebuilding `model.features` or `model.forward_returns`;
- mining `preferred.contract_terms`;
- running the idempotent classification repairs.

Do not use when:

- the upstream raw data is missing or stale (`data-acquisition`);
- the change is a schema or migration (`data-storage-schema`);
- the change is a score weight or the composite (`financial-scoring`);
- the task is the full ordered nightly (`data-refresh-operations`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `raw.*` | yes | The stored payloads this stage reads. |
| Table | `reference.securities` | yes | The dividend universe and classifications. |
| Command | `python -m scripts.build_features` | yes | Feature build; `--days` must exceed the 252-day lookback. |
| Command | `python -m scripts.build_forward_returns` | yes | 252-trading-day forward total returns. |
| Command | `python -m scripts.populate_fundamentals` | yes | Offline XBRL-derived periods. |
| Command | `python -m scripts.populate_clean_ticker_profile` | no | Normalized CIK/ticker row. |
| Command | `python -m scripts.populate_clean_company_profile` | no | Company, officer and corporate-action split. |
| Command | `python -m scripts.populate_contract_terms` | no | Preferred liquidation/call terms. |
| Doc | `docs/data-health-workstreams.md` | yes | Point-in-time and look-ahead decisions. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Confirm the upstream tables are populated for the target universe. Missing
   upstream data is a stop condition, not something to synthesize.
3. Run the stages in dependency order, one at a time:
   - `python -m scripts.populate_fundamentals`
   - `python -m scripts.build_features --days <N>`
   - `python -m scripts.build_forward_returns`
   - `python -m scripts.populate_clean_ticker_profile`
   - `python -m scripts.populate_clean_company_profile`
   - `python -m scripts.populate_contract_terms`
4. Keep the point-in-time contract: a feature row dated D may use only data
   available at D. Never join a later vintage to an earlier row.
5. Keep `--days` larger than the 252-trading-day price lookback behind
   volatility and momentum, or the incremental rebuild leaves those features
   structurally empty.
6. Run the idempotent repairs only when classification is wrong:
   `python -m scripts.repair_security_classification` and
   `python -m scripts.repair_ticker_profile_sec_terms`; use `--dry-run` first.
7. Run the matching tests before reporting success.

## Outputs

- `clean.ticker_profile`, `clean.company_profile`, `clean.company_officer`,
  `clean.corporate_action`;
- `fundamentals.periodic_financials`;
- `model.features`, `model.forward_returns`;
- `preferred.contract_terms`;
- repaired rows in `reference.securities` / `raw.ticker_profile`.

## Verification

Pass when:

- the stage exits 0 and reports the expected row counts;
- the relevant tests pass:

  ```bash
  python -m pytest -q tests/test_features.py tests/test_feature_carry_forward.py \
    tests/test_fundamentals_and_predictions.py tests/test_build_forward_returns.py
  ```

- `model.features` has no duplicate `(security_id, as_of_date)` rows and the
  252-day features are present for the intended window;
- `model.forward_returns` contains only complete 252-trading-day windows;
- a repair run reports the same counts in `--dry-run` and in the write.

## Failure handling

- Upstream table empty: stop; route to `data-acquisition` with the ticker/date
  scope.
- Look-ahead or vintage violation: stop and report; do not ship a feature that
  reads a later period.
- Feature window too short: raise `--days`; do not accept structurally NULL
  momentum/volatility.
- Contract mining returns nothing for a security: report the coverage gap; do
  not copy terms from another series.
- A repair would move many rows unexpectedly: stop and present the dry-run
  count before writing.

## Source of truth

- `src/crispdm/features.py`
- `src/crispdm/feature_window.py`
- `src/crispdm/fundamentals.py`
- `src/crispdm/doc_clauses.py`
- `scripts/populate_clean_*.py`
- `scripts/populate_fundamentals.py`
- `scripts/build_features.py`
- `scripts/build_forward_returns.py`
- `docs/data-health-workstreams.md`

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
