# Investment Analysis Worksheet — Roadmap

This document records the audit that led to the Draft/Final split and lists the work
that remains. The worksheet itself (`app/analysis_schema.py` +
`app/views/investment_analysis.py`) is the source of truth for field behaviour;
`docs/InvestmentAnalysisWorkflow.md` mirrors it and is checked by
`tests/test_workflow_doc.py`.

## Why this exists

The worksheet had grown to 18 steps and 158 fields. An audit of the saved-worksheet path
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

### Phase 2 — store-level guarantees (done)

- **Status transitions.** A Final cannot be demoted to Draft by an ordinary save.
  `store.update` locks the row (`SELECT ... FOR UPDATE`), reads its current status, and
  raises `StatusTransitionError` unless the caller passes `reopen=True`. The page renders
  a "Reopen this Final worksheet as a Draft" checkbox when, and only when, a Final row is
  open and Draft is selected, so the intent is explicit and visible.
- **Versioned payload.** Migration V0088 adds
  `analysis.investment_analysis_revisions`, an append-only table written by an
  `AFTER INSERT OR UPDATE` trigger. Every save (from the UI or any script) is kept, so the
  concurrency refusal is recoverable and the page can show a History panel.
- **Recommendation integrity — deliberately left in the app.** The "steps 1-17 complete
  before a recommendation" rule is enforced by `validate_draft`/`validate`, not by a SQL
  trigger. The required-field set is owned by `app/analysis_schema.py`; re-expressing the
  57 required-field names in plpgsql would create a second source of truth that drifts.
  The store package (`src/`) must not import the app, so the rule stays where the schema
  lives. A writer that bypasses the app is now *auditable* instead: its save lands in the
  revisions table with `saved_by` and `saved_at`.

### Phase 3 — auditability (done)

- **Field-level diff.** `analysis_schema.diff_payloads(before, after)` returns each field
  that changed between two payloads, with human labels and display strings, in workflow
  order; `format_change` renders one line per change. The sidebar History panel pairs each
  revision with its predecessor and lists what that save altered, so the evolution of a
  thesis is visible, not only its final state.
- **Export metadata.** `to_markdown` takes optional `status`, `saved_by` and `saved_at`
  and emits them as a provenance header. The page passes the open row's values, so an
  exported report identifies its status and last editor.
- **Data-source citations.** Every section now carries a `sources` textarea (auto-added
  like the confidence block, and explicit on the sections without one). It is optional
  rather than required — forcing a citation to save a draft would block work in progress —
  but it is exported in Markdown and documented in the workflow, closing the "cite your
  sources" requirement with somewhere to put them.

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
