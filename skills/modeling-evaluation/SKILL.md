---
name: modeling-evaluation
description: "Use when revisiting the ML label, running the walk-forward gate, or interpreting a Go/No-Go checkpoint. Do not use to promote a model into production; the ML model is not adopted."
version: 1
risk: write
owner: analysis
entrypoint: none  # none|fixed|list
tags: []
---

# Modeling and Evaluation

Keep the ML diagnostics reproducible and honest. The rule-based composite is
the product; this skill never promotes a walk-forward model into scoring.

## When to use / when not to use

Use when:

- a label cohort is mature enough to evaluate;
- re-running the walk-forward gate after a feature or data change;
- demonstrating the gate without data (`dry_run_walk_forward`);
- interpreting a checkpoint or an `audit.model_runs` verdict.

Do not use when:

- the task is to change the composite (`analysis-scoring`);
- labels would be written on a partial run;
- someone asks to "turn on" the model: that is a product decision, not an
  execution step.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Env | `MIN_RECALL` | no | Gate, default 0.30. |
| Table | `model.features.target_sustainable_dividend` | yes | Offline labels; never fabricated. |
| Table | `model.features`, `model.forward_returns` | yes | Evaluation inputs. |
| Command | `python -m scripts.evaluate_walk_forward` | yes | The real-data gate. |
| Command | `python -m scripts.dry_run_walk_forward` | no | Synthetic proof, no DB/network writes. |
| Doc | `docs/model-labeling-plan.md` | yes | Label ownership and horizon. |
| Doc | `docs/data-health-workstreams.md` | yes | Acceptance policy and known defects. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Confirm the label cohort is complete: labels require a stable, full-universe
   feature frame and a fully elapsed 365-day horizon.
3. If no real cohort exists, prove the mechanism only:

   ```bash
   python -m scripts.dry_run_walk_forward
   ```

4. For the real gate:

   ```bash
   python -m scripts.evaluate_walk_forward
   ```

   Optionally pass `--folds N` to require every expanding-window fold to clear
   the gate. The result is written to `data/walk_forward_checkpoint.json` and
   `audit.model_runs`.
5. Read the verdict as `GO` or `NO-GO` from `gate_passed`/`readiness`, not from
   exit alone. A GO also requires feature completeness.
6. Report the metrics, the label cohort size, the horizon and the contract
   version. A prior checkpoint under a different contract is not evidence.
7. Record the outcome; do not change production scoring as a result.

## Outputs

- `data/walk_forward_checkpoint.json`.
- A row in `audit.model_runs` with metrics, gate detail and readiness.
- No change to `model.scores` or the composite.

## Verification

Pass when:

- `tests/test_walk_forward_checkpoint.py`, `tests/test_dry_run_walk_forward.py`
  and `tests/test_label_targets.py` pass;
- the checkpoint records its contract/feature version and gate detail;
- fewer than 10 labeled rows is reported as an informational exit 0 with no
  checkpoint, not as a pass;
- a NO-GO is reported as NO-GO; do not relabel it.

## Failure handling

- Labels missing or immature: stop; do not label a partial run and do not
  backfill a label by hand.
- A fold cannot score its test block: report it; do not count it as measured.
- Stale checkpoint from an older contract: ignore it for the current decision
  and say so.
- Someone requests model promotion after a NO-GO: stop and escalate to the
  product owner; the decision is recorded in `docs/requirements.md`.
- Gate passes: still do not switch the composite without an explicit product
  decision and a documented rollout.

## Source of truth

- `src/crispdm/model.py`
- `scripts/label_targets.py`
- `scripts/evaluate_walk_forward.py`
- `scripts/dry_run_walk_forward.py`
- `docs/model-labeling-plan.md`
- `docs/requirements.md` (section 4)
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
