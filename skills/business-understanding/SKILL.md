---
name: business-understanding
description: "Use when defining or changing the screening universe, factor weights, acceptance criteria, or the product boundary, and when recording that decision. Do not use for implementation-only changes that do not alter the agreed business rules."
version: 1
risk: write
owner: product
entrypoint: none  # none|fixed|list
tags: []
---

# Business Understanding

Translate the investment objective into rules that code can enforce, and record
the decision so it survives knowledge loss. This is the CRISP-DM entry point.

## When to use / when not to use

Use when:

- changing the dividend universe membership rule;
- changing a factor weight, threshold or ranking definition;
- adding or removing an acceptance criterion;
- deciding whether the ML model is in or out of the product.

Do not use when:

- the change is a bug fix with no rule change (`data-transformation` or
  `financial-scoring`);
- the task is UI copy only, with the rule unchanged;
- the request conflicts with an existing recorded decision and has no owner
  sign-off.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/requirements.md` | yes | The light requirements artifact. |
| Doc | `README.md` | yes | Product framing and data flow. |
| File | `src/crispdm/scoring.py` | yes | Executable weights and coverage floor. |
| File | `src/crispdm/config.py` | yes | Universe and evaluation settings. |
| File | `app/views/screener.py` | yes | User-visible caption that must match. |
| Table | `reference.securities` | yes | The `dividend = TRUE AND active = TRUE` universe. |

## Procedure

1. Read `docs/requirements.md` and the relevant code. State the current rule
   and where it is enforced.
2. Write the decision before the implementation: what changes, why, who owns
   it, and what evidence would reverse it.
3. Update, in one change:
   - the rule in code (`scoring.py`, `config.py`, or the universe query);
   - `docs/requirements.md`;
   - the user-visible caption in `app/views/screener.py`, when weights or
     definitions are shown;
   - the test that pins the rule.
4. Keep the universe definition explicit: a security is in scope only when
   `reference.securities.dividend = TRUE AND active = TRUE`. Do not widen it
   implicitly to make a name appear.
5. Keep the ML decision explicit: the rule-based composite is the product; a
   model is not promoted without a new recorded decision.
6. Run the weight and view tests.

## Outputs

- Updated `docs/requirements.md` with the decision and rationale.
- Code and test changes that enforce the same rule.
- Updated UI caption when a user-visible weight or definition moved.
- No data writes.

## Verification

Pass when:

- `tests/test_scoring.py` passes, including the weights-sum-to-1 invariant;
- the requirements text, the code constant and the UI caption agree;
- the universe rule is still backed by the partial index and the dividend
  recency check;
- the change records who decided and the date.

## Failure handling

- The request changes a weight but not the decision record: stop; add the
  record first.
- The text and code disagree: code wins until both are corrected in the same
  change.
- The request widens the universe for one security: stop; that is either a data
  defect or a rule change, not a special case.
- The request promotes the ML model: require an explicit product decision and
  an updated `docs/requirements.md`; a passing gate alone is not enough.

## Source of truth

- `docs/requirements.md`
- `README.md`
- `src/crispdm/scoring.py`
- `src/crispdm/config.py`
- `src/crispdm/dividend_universe.py`
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
