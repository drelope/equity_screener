# Investment Analysis Worksheet — Roadmap

This document records the audit that led to the Draft/Final split and lists the work
that remains. The worksheet itself (`app/analysis_schema.py` +
`app/views/investment_analysis.py`) is the source of truth for field behaviour;
`docs/InvestmentAnalysisWorkflow.md` mirrors it and is checked by
`tests/test_workflow_doc.py`.

## Why this exists

The worksheet had grown to 18 steps and 140 fields. An audit of the saved-worksheet path
surfaced a handful of correctness gaps: the most important was that a **Draft could not
be saved at all** — every save ran the full Final rule set, so an analyst working
step-by-step lost everything until every required field was filled. The second was that
two people editing the same worksheet silently overwrote each other.

## Status

### Phase 0 — schema hardening (done)

- **Draft/Final validation split.** `validate_draft()` accepts a partial worksheet:
  structural shape only, at least one filled field, and the sequence gate. `validate()`
  is the full Final rule set. `app/analysis_schema.py`.
- **Cross-field rules.** `scenarios.scenario_probabilities` must be exactly three numbers
  summing to 100 once it contains digits; `analog.base_rate` must be a single percentage
  in 0-100 once it contains digits. Free text without digits is left alone so the analyst
  is not blocked mid-sentence.
- **Doc↔schema parity.** `tests/test_workflow_doc.py` parses
  `docs/InvestmentAnalysisWorkflow.md` and asserts the 18 step ids and every field id
  match `app/analysis_schema.py` in both directions.
- **Progress helpers.** `section_completion()` (filled/total per step) and
  `prior_steps_complete()` (are steps 1-17 done).

### Phase 1 — the save path (done)

- **Draft saves work.** `app/views/investment_analysis.py` routes the Status selectbox to
  `validate_draft()` for Draft and `validate()` for Final. An empty worksheet is refused
  even as a Draft; a `recommendation` is refused while steps 1-17 are incomplete.
- **Optimistic concurrency.** Each open worksheet tracks its row's `updated_at`
  (`ia_updated_at`). Saving re-reads the row first: if it was deleted the existing
  "no longer exists" message is shown; if it changed the save is refused with "changed in
  another tab" instead of overwriting the newer version.
- **Per-step progress.** Section headers show `filled/total` required fields, and the
  first incomplete section opens automatically. The final section shows a warning while
  steps 1-17 are incomplete.
- **Tests.** Draft/final split, sequence gate, cross-field rules and section progress in
  `tests/test_analysis_schema.py`; empty-draft refusal, sequence gate and concurrent-edit
  refusal in `tests/test_streamlit_app.py`.

## Remaining

### Phase 2 — store-level guarantees (not started)

- **Status transitions.** `store.update` currently accepts any status; a Final can be
  demoted to Draft without review. Add a transition check (Final → Draft should require
  an explicit intent, and the column CHECK can only see the enum).
- **Recommendation integrity.** The `recommendation` CHECK only constrains the enum; the
  "steps 1-17 complete" rule lives in the app. Moving it into the store (or a trigger)
  would protect the data even if another writer bypasses the UI.
- **Versioned payload.** Every save overwrites `payload`. Keeping an append-only revision
  table would make the concurrency refusal recoverable ("reopen the newer version") rather
  than a dead end.

### Phase 3 — auditability (not started)

- **Field-level diff.** Record which fields changed between revisions, so a reviewer can
  see the evolution of a thesis rather than only its final state.
- **Export metadata.** `to_markdown` does not emit status, timestamps or the operator;
  including them makes the exported document self-identifying.
- **Data-source citations.** The workflow requires every quantitative claim to cite a
  source, but no field captures it. Add a citations block (or per-field annotations).

### Phase 4 — assisted analysis (not started)

- **LLM-assisted draft.** The Markdown export is designed to be pasted into an external
  model; a supported "generate a draft from the warehouse context" path is the obvious
  next step, gated on the same Final rules so a model cannot skip the workflow.
- **Recommendation history.** Track Buy/Add/Hold/Trim/Sell over time per security to
  audit the track record of the calls themselves.

## Rules for future changes

- Any change to sections, field ids, types or options must update
  `docs/InvestmentAnalysisWorkflow.md` in the same commit; the parity test will fail
  otherwise.
- New validation rules belong in `validate()` (Final) unless the analyst genuinely needs
  to save a partial worksheet with that rule broken — in that case add them to
  `validate_draft()` and document why.
- Anything that writes to `analysis.investment_analyses` must go through the Draft/Final
  split and the `updated_at` concurrency guard, not around them.
