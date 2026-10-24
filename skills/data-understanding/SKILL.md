---
name: data-understanding
description: "Use when profiling source coverage, freshness, provenance or gaps before acquisition or modelling; assessing whether a new source or field is viable; or explaining why a table is empty. Do not use when fetching data, building features, or changing schema."
version: 1
risk: read
owner: data-engineering
entrypoint: none  # none|fixed|list
tags: []
---

# Data Understanding

Profile what is stored, where it came from, how fresh it is, and what is
missing. This skill produces evidence and a recommendation; it never writes to
the warehouse.

## When to use / when not to use

Use when:

- assessing whether a source or field can support a feature or screen;
- explaining a coverage, freshness or `NULL` gap;
- comparing provider values for the same fact;
- preparing an acquisition or schema change.

Do not use when:

- the answer is already in `docs/data-acquisition.md` or the README schema
  reference;
- the task is to fetch or repair data (`data-acquisition`);
- the task is to build derived tables (`data-transformation`);
- the task requires a schema change (`data-storage-schema`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Doc | `docs/data-acquisition.md` | yes | Source cadence and lookback rules. |
| Doc | `docs/data-health-workstreams.md` | no | Known gaps and prior decisions. |
| Doc | `README.md` | yes | Schema reference and table ownership. |
| Command | `python -m scripts.verify_nightly_run --json` | no | Freshness and coverage evidence. |
| File | `src/crispdm/explorer.py` | no | The allowlisted, read-only table browser. |

Read-only relations of interest: `reference.securities`, `raw.market_data`,
`raw.dividend_data`, `raw.companyfacts`, `raw.sec_documents`,
`raw.macro_series`, `fundamentals.periodic_financials`, `model.features`,
`audit.source_lineage`, `audit.data_quality`.

## Procedure

1. Run the preflight from `SYSTEM.md`. The `migrate --check` step is
   informational for this read-only skill; a pending migration is reported, not
   applied.
2. Read the source-of-truth docs for the source and table. Do not assume a
   cadence from a column name.
3. Collect evidence with one of:
   - `python -m scripts.verify_nightly_run --json` for freshness, coverage and
     quality findings;
   - the read-only Data Explorer (`app/views/data_explorer.py`) for table
     profiles and bounded samples.
4. For every quantitative claim, record the relation, the filter and the
   observation date.
5. Separate **observed** from **inferred**. Mark unverified assumptions as
   `UNVERIFIED`.
6. State the gap, its impact on the requested feature/screen, and the smallest
   next action. Route that action to the owning skill.

## Outputs

- No table writes.
- A short findings report in the response, or `artifacts/runs/<run-id>/summary.md`
  once the executor exists.
- Optional proposed follow-up, routed to `data-acquisition`,
  `data-transformation`, or `data-storage-schema`.

## Verification

The report passes when:

- every number names its relation, filter and as-of date;
- every claim is marked observed or `UNVERIFIED`;
- no value was inferred from a code comment or a stale doc;
- the counts can be reproduced by repeating the stated query.

If `python -m scripts.verify_nightly_run --json` is used, its exit code is
evidence, not a crash: `0` means all checks pass; `1` means attention is needed
and the findings must be reported.

## Failure handling

- Database unreachable: stop. Do not substitute sample values or prior chat
  output.
- Table missing: report the migration that creates it; do not create it.
- Conflicting provider values: show both with provenance and stop before
  choosing one.
- Coverage below threshold: report the finding and route to acquisition; do not
  widen a threshold to make it pass.

## Source of truth

- `docs/data-acquisition.md`
- `docs/data-health-workstreams.md`
- `README.md` (schema reference)
- `src/crispdm/explorer.py`
- `scripts/verify_nightly_run.py`

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
- **Scoring/labeling policy:** route to `analysis-scoring` or `modeling-evaluation` per boundaries above.

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
