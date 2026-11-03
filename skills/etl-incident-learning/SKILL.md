---
name: etl-incident-learning
description: "Use when an ETL change failed, was rolled back or surprised you and the cause should be recorded as a guarded lesson, or before a data-changing ETL change to recall the lessons for its area. Do not use to repair data, run the pipeline or decide business policy."
version: 2
risk: write
owner: operations
entrypoint: none
tools: []
tags: [etl, learning, incidents, lifecycle]
---

# ETL Incident Learning

Record the root cause of an ETL incident as a lesson with a guard, and recall the relevant
lessons before the next change. Architecture: [`docs/etl-learning-architecture.md`](../../docs/etl-learning-architecture.md).

## When to use / when not to use

Use when:

- a stage failed after tests passed, a change was rolled back, or a fix reversed an earlier one;
- you are about to change data, classification, identities or stage order and want the lessons
  for that area first;
- reviewing `open` lessons in an area you are touching.

Do not use when:

- the pipeline must be run or repaired (`data-refresh-operations`);
- a schema change is needed (`data-storage-schema`);
- the question is which securities belong in scope (`business-understanding`).

## Runner

- **Mode:** Manual only (do not guess argv). Edits are to `docs/etl-lessons/` only.
- **Confirmation:** none needed; the skill touches documentation and never the database.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill is allowed.
- [ ] `git status --short` shows no unrelated edits in `docs/etl-lessons/`.
- [ ] The incident has evidence: a command and its counts or error, not a recollection.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/etl-lessons/INDEX.md` | yes | The ledger and its statuses. |
| Doc | `docs/etl-learning-architecture.md` | yes | The loop and the rules. |
| Evidence | the failing command, counts before and after, the commit | yes | Quote it; do not paraphrase. |

## Procedure

1. **Recall first.** Run the recall command with words naming the planned change and run each
   recurrence check it prints; open lessons come first. Report which you ran and the result.

   ```bash
   python -m scripts.lessons_audit --recall stage 1 retype
   python -m scripts.lessons_audit --recall openbb dividend    # provider ceilings (L012)
   ```
2. **Capture.** State the symptom with the evidence.
3. **Root cause.** Name the mechanism, not the trigger. If you cannot, mark the lesson `open`.
   Before building a rule on a premise, compare it with the source (L010): a premise taken
   from stored data can be an artifact of how the data was adjusted.
4. **Guard.** Add a refusal, a test that fails on the broken form (break the code to prove it),
   or a dry-run rule. Link the guard in backticks. If none is possible, status is `open`.
5. **Retract, do not delete.** If an earlier lesson or rule proved wrong, write a new lesson
   with what was believed, what the evidence showed and the corrected method, and remove the
   wrong rule in its own commit.
6. **Record.** Add `docs/etl-lessons/L###-short-name.md` using the fields of an existing
   lesson and one row to `INDEX.md`.
7. Run the verification below.

## Outputs

- One new or amended file in `docs/etl-lessons/` and its index row.
- No database writes, no artifacts.

## Verification

**Pass if:**
- [ ] `python -m scripts.lessons_audit` exits 0.
- [ ] A `guarded` lesson names a guard that exists and a recurrence check that was run.
- [ ] `python -m pytest -q tests/test_lessons_audit.py` passes.
- [ ] `python -m scripts.skill_audit --skill etl-incident-learning --phase verify` exits 0.
- [ ] No secret value, host path or unresolved marker was written.

```bash
python -m scripts.lessons_audit
python -m pytest -q tests/test_lessons_audit.py
```

## Failure handling

- No evidence: stop and ask for the command and counts; do not write a lesson from memory.
- No guard possible: record it as `open` and say so; never mark it `guarded` to close it.
- Two lessons share a cause: amend the existing one.
- A cap or threshold from one provider is being reused for another: measure the new provider's valid range first (L012).
- A result is gross of costs: say so, and report the after-cost figure with its sensitivity (L011).

## Handoffs

- A data fix is needed → `data-refresh-operations` (include the lesson and its check).
- A schema or constraint change is the guard → `data-storage-schema`.
- Scope or universe policy is in question → `business-understanding`.
- Secret risk → `security-compliance` (do not share values).

## Stop conditions

- [ ] A lesson is being marked `guarded` without an existing guard.
- [ ] The change would edit anything outside `docs/etl-lessons/` and the lessons audit.
- [ ] A secret would be printed, logged or committed.

## Evidence required

- The commands run with exit codes, including the recurrence checks.
- The lesson file, its index row and the audit result.

## Source of truth

- `docs/etl-learning-architecture.md`
- `docs/etl-lessons/INDEX.md`
- `scripts/lessons_audit.py`
