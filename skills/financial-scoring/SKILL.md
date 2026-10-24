---
name: financial-scoring
description: "Use when changing factor weights, the composite score, ranking, regime weights or prediction thresholds, or when re-scoring a historical date. Do not use for investment validation, KPI/risk interpretation or reporting (financial-analysis), the worksheet (investment-analysis), or model evaluation."
version: 1
risk: write
owner: analysis
entrypoint: none  # none|fixed|list
tags: [scoring, ranking]
---

# Financial Scoring

Own the rule-based composite, its component percentiles, rankings and the
`model.predictions` threshold. The composite is the product; it is not a
calibrated probability. Interpretation, risk and reporting belong to
`financial-analysis`.

## When to use / when not to use

Use when:

- changing `WEIGHTS` or a component formula;
- re-scoring a historical date after a policy change;
- changing the regime weight matrix or the prediction threshold;
- explaining coverage, a NULL component or a ranking move.

Do not use when:

- the feature inputs are wrong (`data-transformation`);
- the task is the walk-forward model gate (`modeling-evaluation`);
- the task is investment validation, KPI/risk interpretation or a report
  (`financial-analysis`);
- the task is the 18-step worksheet or a Final recommendation
  (`investment-analysis`);
- the task is UI presentation only (the Streamlit view).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `model.features` | yes | Point-in-time factor inputs. |
| File | `src/crispdm/scoring.py` | yes | `WEIGHTS`, components, coverage floor. |
| File | `src/crispdm/regime.py` | yes | Regime weight matrix. |
| File | `docs/requirements.md` | yes | The agreed weights and acceptance criteria. |
| Command | `python -m scripts.score_rank` | yes | Writes scores, predictions, rankings. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Read `docs/requirements.md` and confirm the weight decision is recorded
   there before changing code. Weights must sum to 1; the tests enforce it.
3. Change the smallest piece: one weight set, one component, or one threshold.
4. Re-score the affected date(s):

   ```bash
   python -m scripts.score_rank --as-of YYYY-MM-DD --prune-superseded
   ```

   The nightly passes `--prune-superseded`; a replay defaults to it unless
   `--keep-superseded` is given. Use `--apply-regime-weights` only when the
   regime layer is the intended change.
5. For a policy change, recompute every affected historical date, not only the
   newest one. Older dates are point-in-time history.
6. Update the Streamlit caption/requirements text when a user-visible weight or
   definition changes.
7. Run the scoring tests and the view test.

## Outputs

- `model.scores`, `model.predictions`, `model.rankings` for the scored
  `as_of_date`.
- Updated weights/thresholds and, when user-visible, the requirements/UI
  caption.

## Verification

Pass when:

- `tests/test_scoring.py` passes, including the weights-sum-to-1 assertion;
- `tests/test_score_pruning.py`, `tests/test_regime.py` and
  `tests/test_regime_pipeline.py` pass when the relevant path changed;
- `tests/test_current_predictions_view.py` passes when the output contract
  changed;
- coverage is reported against `WEIGHTS`; a security below
  `MIN_PRESENT_WEIGHT` is not silently scored as zero;
- `model.predictions` rows at the scored date agree with `model.scores`.

## Failure handling

- Weights do not sum to 1: stop; that is a test failure, not a rounding issue.
- A component is all NULL: report the upstream gap; do not substitute a
  constant.
- Pruning would delete rows from an older date: stop; only the scored date may
  be pruned.
- A replay changes historical rankings: report the diff and confirm it is the
  intended policy effect.
- Do not describe `model.predictions` or the composite as a probability or a
  calibrated forecast.

## Source of truth

- `src/crispdm/scoring.py`
- `src/crispdm/regime.py`
- `src/crispdm/regime_pipeline.py`
- `scripts/score_rank.py`
- `docs/requirements.md`
- `app/views/screener.py`

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
