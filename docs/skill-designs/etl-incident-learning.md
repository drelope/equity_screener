# Skill Design: `etl-incident-learning`

Status: verified
Owner: operations
Risk: write
Source of truth: `skills/etl-incident-learning/SKILL.md`, `docs/etl-learning-architecture.md`,
`docs/etl-lessons/INDEX.md`, `scripts/lessons_audit.py`
Token budget: `SKILL.md <= 160 lines / 8,000 chars; each reference <= 260 lines / 12,000 chars`
Open questions: none

## Clarify

- **Problem:** ETL incidents were fixed once and then forgotten. In one session a partial title
  list retyped 250 stocks, a guard silently did not apply, and a mocked test hid a driver
  error. Each lesson lived only in a commit message.
- **Decision supported:** whether a planned data-changing change repeats a known failure, and
  what to record when a new one is found.
- **Audience:** engineer or agent changing the ETL, and the reviewer.
- **In scope:** recording a lesson with its guard, recalling lessons for an area, auditing the
  ledger.
- **Out of scope:** repairing data, running the pipeline, schema changes, business policy.
- **Authoritative evidence:** nine lessons in `docs/etl-lessons/`, each from an incident with
  commands and counts, and its guard in `scripts/` or `tests/`.
- **Assumptions and validation:** a lesson is only useful if it is enforced. Validated by the
  audit refusing a `guarded` lesson whose guard path does not exist.
- **Success criteria:** `python -m scripts.lessons_audit` exits 0 and the skill audit passes.
- **Tool scope and security class:** `write`, documentation only, no tools, no database.
- **Token budget:** `SKILL.md` well under 160 lines.

## Design

- **Trigger and non-trigger:** see the skill's `description` and its use / do-not-use lists.
- **Inputs / outputs:** the ledger and the incident evidence in; one lesson file and an index
  row out.
- **Read-write boundary:** writes `docs/etl-lessons/` only; never the warehouse.
- **Handoffs:** `data-refresh-operations`, `data-storage-schema`, `business-understanding`,
  `security-compliance`.
- **Failure modes and stop conditions:** no evidence, no possible guard (record `open`), a
  guarded claim without a guard, anything outside `docs/etl-lessons/`.
- **Reference plan:** none; the architecture is a linked document, not copied into the skill.
- **Verification commands and pass conditions:** `python -m scripts.lessons_audit` exit 0;
  `tests/test_lessons_audit.py` passes; `skill_audit` passes for this skill and `--all`.
- **Accepted risk:** the audit checks that a guard exists, not that it is good. Mitigated by
  requiring a named recurrence check per lesson and by review.

## Plan

- **Files to add:** `skills/etl-incident-learning/SKILL.md`,
  `docs/skill-designs/etl-incident-learning.md`, `docs/etl-learning-architecture.md`,
  `docs/etl-lessons/` (index and nine lessons), `scripts/lessons_audit.py`,
  `tests/test_lessons_audit.py`.
- **Files to modify:** `SYSTEM.md` (inventory), `docs/file-based-agentic-workflow.md` (routing
  and inventory, skill count 21 to 22).
- **Files to delete:** none.
- **Tests to add or change:** `tests/test_lessons_audit.py`; any skill-count assertion.
- **Rollback:** `git revert` the commit; nothing outside documentation and one script changes.
- **Acceptance mapping:** ledger integrity maps to `test_the_real_ledger_is_consistent`; a
  guarded lesson needs a real guard maps to `test_a_guarded_lesson_whose_guard_is_missing_fails`.

## Code

- **Files changed:** those listed in the plan.
- **Tests added:** eight in `tests/test_lessons_audit.py`.
- **Deviations from the plan:** none.

## Verify

- **Commands and exit codes:** recorded in the change that adds this skill.
- **Audit result:** PASS.
- **Targeted test result:** pass.
- **Ruff result:** exit 0.
- **Residual risks:** two lessons are `open` (line endings, rights classification) and say so.

## Gate log

| Phase | Result | Evidence |
|---|---|---|
| clarify | pass | Problem, boundary, evidence and success criteria recorded above |
| design | pass | Contract, handoffs and accepted risk recorded above |
| plan | pass | File, test and rollback list above |
| code | pass | Skill, ledger, audit script and tests |
| verify | pass | Audit PASS, ledger audit exit 0, targeted tests pass, ruff exit 0 |
