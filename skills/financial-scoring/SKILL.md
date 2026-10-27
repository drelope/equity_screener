---
name: financial-scoring
description: "Use when implementing an approved weight, composite, ranking, regime or threshold change, or when replaying scores for a historical date. Do not use for policy decisions, investment validation or reporting, the worksheet, or model evaluation."
version: 1
risk: write
owner: analysis
entrypoint: none
tools: []
tags: [scoring, ranking, lifecycle]
---

# Financial Scoring

Own the rule-based composite, component percentiles, rankings and the
`model.predictions` threshold. The composite is the product; it is not a
calibrated probability. Policy is decided by `business-understanding`;
interpretation, risk and reporting belong to `financial-analysis`.

## When to use / when not to use

Use when:

- implementing a weight or component change approved in `docs/requirements.md`;
- replaying a historical date after an approved policy change;
- implementing a regime weight matrix or prediction-threshold change;
- explaining coverage, a NULL component or a ranking move.

Do not use when:

- deciding weights, universe or acceptance criteria (`business-understanding`);
- the feature inputs are wrong (`data-transformation`);
- the walk-forward model gate (`modeling-evaluation`);
- investment validation, KPI/risk interpretation or a report (`financial-analysis`);
- the 18-step worksheet or a Final recommendation (`investment-analysis`);
- UI presentation only.

## Runner

- **Mode:** Manual only. There is no executable entrypoint; never guess argv.
- **Confirmation:** `risk: write`; write only after an approved policy decision.

## Preflight

- [ ] Read `SYSTEM.md` and confirm ownership; review `git status --short`.
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches schema.
- [ ] Confirm the weight decision is recorded in `docs/requirements.md`.
- [ ] Do not read `.env`; check env names only.
- [ ] Confirm no data, feature or policy change is bundled into the replay.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `model.features` | yes | Point-in-time factor inputs. |
| File | `src/crispdm/scoring.py` | yes | `WEIGHTS`, components, coverage floor. |
| File | `src/crispdm/regime.py` | yes | Regime weight matrix. |
| File | `docs/requirements.md` | yes | Approved weights and acceptance criteria. |
| Command | `python -m scripts.score_rank` | yes | Writes scores, predictions and rankings. |

## Procedure

1. Run the preflight.
2. Confirm the policy decision, owner and date are recorded in
   `docs/requirements.md` before changing code. Weights must sum to 1; tests
   enforce it.
3. Change the smallest piece: one weight set, component, threshold or regime
   input.
4. Re-score the affected date(s) with
   `python -m scripts.score_rank --as-of YYYY-MM-DD --prune-superseded`.
   A replay defaults to `--prune-superseded` like the nightly unless
   `--keep-superseded` is given; use `--apply-regime-weights` only when the
   regime layer is the intended change.
5. For a policy change, recompute every affected historical date, not only the
   newest one. Older dates are point-in-time history.
6. Update the Streamlit caption/requirements text when a user-visible weight
   or definition changes.
7. Run the scoring tests and the relevant view test. Report the historical
   rank diff and confirm it is the intended policy effect.
8. Hand off interpretation and reporting to `financial-analysis`.

## Outputs

- `model.scores`, `model.predictions` and `model.rankings` for the scored `as_of_date`.
- Updated weights/thresholds and, when user-visible, the requirements/UI caption.
- A replay diff when historical rankings change.

## Verification

Pass when `tests/test_scoring.py` (including weights-sum-to-1) passes;
`tests/test_score_pruning.py`, `tests/test_regime.py` and
`tests/test_regime_pipeline.py` pass when the relevant path changed;
`tests/test_current_predictions_view.py` passes when the output contract
changed; coverage is reported against `WEIGHTS`; and `model.predictions` rows
at the scored date agree with `model.scores`.

```bash
python -m scripts.skill_audit --skill financial-scoring
python -m pytest -q tests/test_scoring.py tests/test_score_pruning.py \
  tests/test_regime.py tests/test_regime_pipeline.py
```

## Failure handling

- Weights do not sum to 1: stop; it is a test failure, not rounding.
- No recorded policy decision: stop and route to `business-understanding`.
- A component is all NULL: report the upstream gap; do not substitute zero.
- Pruning would delete rows from an older date: stop; only the scored date may be pruned.
- A replay changes historical rankings: report the diff and confirm the policy effect before claiming success.
- Never describe `model.predictions` or the composite as a probability or calibrated forecast.

## Handoffs

- **Weight/universe/acceptance policy:** route to `business-understanding`.
- **Feature or fundamentals defect:** route to `data-transformation`.
- **Missing source data:** route to `data-acquisition`.
- **Schema drift or migration:** route to `data-storage-schema`.
- **Nightly freshness or health:** route to `observability-nightly-verification`.
- **Interpretation, risk or reporting:** route to `financial-analysis`.
- **ML gate:** route to `modeling-evaluation`.
- **Secrets or access:** route to `security-compliance`.

## Stop conditions

- [ ] Task is outside this skill's scope.
- [ ] The weight change has no approved `docs/requirements.md` decision.
- [ ] Weights do not sum to 1.
- [ ] A score/rank would treat NULL or an under-covered security as zero.
- [ ] Pruning would remove rows from an older date.
- [ ] A data, schema or feature change is bundled into the scoring run.
- [ ] The composite would be described as a probability.
- [ ] A secret would be printed, logged or committed.
- [ ] Unexpected `git status` changes appear in the scoped area.

## Evidence required

- **Commands:** argv, cwd, exit codes and timestamps.
- **State:** affected tables/rows, scored date and policy decision path.
- **Findings:** weight/definition diff, historical rank diff and coverage.
- **Handoffs:** target skill, reason and evidence.

## Source of truth

- `src/crispdm/scoring.py`, `src/crispdm/regime.py`, `src/crispdm/regime_pipeline.py`, `scripts/score_rank.py`
- `docs/requirements.md`, `app/views/screener.py`

## References

- [Scoring model](references/scoring-model.md) — load when implementing a
  weight, component, coverage, regime or threshold change.
- [Change and replay](references/change-and-replay.md) — load when replaying a
  date, pruning or reviewing a rank diff.

## Context budget

- Always load: this file, the design record and the approved policy decision; load only the reference named by the current change.
- Use tests and code for exact formulas; do not restate them from memory.
