---
name: investment-analysis
description: "Use when working the 18-step investment-analysis worksheet, saving a draft or final recommendation, exporting it, or changing its schema and validation. Do not use for screening or scoring, which are separate views."
version: 1
risk: write
owner: analysis
entrypoint: none  # none|fixed|list
tags: []
---

# Investment Analysis

Drive the structured, 18-step institutional analysis and its recommendation
gate. The code contract is `app/analysis_schema.py`; the analyst-facing
document is `docs/InvestmentAnalysisWorkflow.md`.

## When to use / when not to use

Use when:

- filling or reviewing a worksheet for a security;
- saving a Draft or Final and handling a validation failure;
- exporting Markdown or inspecting revision history;
- changing a section, field, option list or validation rule.

Do not use when:

- the task is the screener or composite score (`financial-scoring`);
- the task is KPI interpretation, portfolio risk or a dashboard report
  (`financial-analysis`);
- the task is raw data acquisition for the worksheet (`data-acquisition`);
- the task is the macro memo inputs (`data-transformation`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| File | `app/analysis_schema.py` | yes | The executable contract. |
| File | `app/analysis_autofill.py` | no | Evidence prefill; never saves. |
| File | `app/llm_client.py` | no | Optional local draft; off by default. |
| Table | `analysis.investment_analyses` | yes | JSONB payload and status. |
| Table | `analysis.investment_analysis_revisions` | yes | Append-only history. |
| Doc | `docs/InvestmentAnalysisWorkflow.md` | yes | Step/field contract. |

## Procedure

1. Run the preflight from `SYSTEM.md`. The worksheet is a write path; confirm
   the migration ledger is clean.
2. Select a security from the dividend universe, or use the ticker handed over
   from the Screener.
3. Work the steps in order, 1-18. Do not record a recommendation before steps
   1-17 have their required fields.
4. For every analytical section, record the confidence assessment and the
   sources behind quantitative claims.
5. Save as **Draft** at any time. Save as **Final** only when validation rules
   8-13 pass (required fields, low-confidence note, three evidence lines,
   three-sentence thesis, scenario probabilities summing to 100, base rate
   0-100).
6. Autofill or LLM draft only prefills the form for review; it never saves and
   never bypasses validation.
7. Treat a concurrent-save refusal as recoverable: re-read the row and compare
   revisions rather than overwriting.
8. When changing the schema, update `app/analysis_schema.py`,
   `docs/InvestmentAnalysisWorkflow.md` and the tests in the same change.

## Outputs

- A row in `analysis.investment_analyses` (Draft or Final, JSONB payload).
- An append-only revision row per save.
- Optional Markdown export.
- No pipeline or score writes.

## Verification

Pass when:

- `tests/test_analysis_schema.py`, `tests/test_analysis_store.py` and
  `tests/test_analysis_autofill.py` pass;
- `tests/test_workflow_doc.py` passes, proving the document and schema ids
  still match;
- a Final save contains every required field and the final thesis;
- the recommendation cannot be recorded while steps 1-17 are incomplete;
- the Markdown export renders sections in workflow order with provenance.

## Failure handling

- Required step incomplete: report the exact missing field ids; do not mark the
  step filled with a placeholder such as `N/A` or `TBD`.
- Concurrent save: re-read and merge; do not force an overwrite.
- Autofill returns weak or missing evidence: leave the field empty and say so;
  do not invent a number.
- LLM draft is enabled: keep it local, review every line, and remember it only
  ever fills a Draft.
- Schema change without the document: stop; both must move together.

## Source of truth

- `app/analysis_schema.py`
- `app/views/investment_analysis.py`
- `app/analysis_autofill.py`
- `src/crispdm/analysis/store.py`
- `docs/InvestmentAnalysisWorkflow.md`
- `docs/InvestmentAnalysisRoadmap.md`
- `docs/peer-base-rate-methodology.md`

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
