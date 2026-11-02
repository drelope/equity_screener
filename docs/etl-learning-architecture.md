# Persistent ETL learning architecture

Purpose: make what one incident teaches survive the session, the person and the context window
that learned it, and make the next change consult it before repeating the mistake.

The ETL here has failed in recurring ways: a partial input list that retypes securities, a
data fix whose ordering matters, a guard that silently did not apply. Each was found by
accident and fixed once. This architecture turns a fix into a record, a check and a habit.

## Four layers

| Layer | What it holds | Where it lives | Who reads it |
|---|---|---|---|
| Capture | The raw incident: symptom, evidence, what was tried | The change's commit message and, when it needed a decision, the design record | The person fixing it |
| Consolidate | One lesson per root cause: symptom, root cause, detection, guard, recurrence check | [`docs/etl-lessons/`](etl-lessons/INDEX.md) | Anyone about to change the ETL |
| Enforce | The guard: a test, a script refusal or a dry-run rule that fails when the mistake recurs | `scripts/`, `tests/`, linked from the lesson | CI and the nightly |
| Recall | A preflight step that matches the planned change to lessons and runs their recurrence checks | The [`etl-incident-learning`](../skills/etl-incident-learning/SKILL.md) skill | The agent or engineer, before a write |

A lesson without a guard is only a note. The ledger therefore has three statuses and one hard
rule: `guarded` requires a guard that exists in the repository, `monitored` names a recurrence
check run by hand, `open` says plainly that nothing prevents recurrence yet.

## The loop

1. **Capture.** When a change fails, is rolled back, or surprises you, stop and write down the
   symptom and the evidence while it is fresh: the command, the counts before and after.
2. **Find the root cause, not the trigger.** "Stage 1 minted rows" is a trigger. "The issuer's
   title list was bound to untitled tickers" is a cause.
3. **Guard it.** Prefer, in order: a refusal in the tool, a test that fails on the broken form
   (prove it by breaking the code), a dry-run rule, a documented check. Link it.
4. **Record it.** One file in `docs/etl-lessons/`, one row in the index.
   `python -m scripts.lessons_audit` must pass.
5. **Recall.** Before a data-changing change, read the index for the area, run each matching
   lesson's recurrence check, and say so in the change.

## What counts as a lesson

Record one when a defect reached the live warehouse, a stage failed after tests passed, an
ordering or coverage assumption was wrong, a tool or formatter silently did something other
than asked, or a decision was reversed. Do not record a typo or a one-off data glitch with no
mechanism behind it.

## What the audit enforces

`scripts/lessons_audit.py` is deterministic and runs in the test suite
(`tests/test_lessons_audit.py::test_the_real_ledger_is_consistent`). It fails on a missing
field, an unknown status, a duplicate id, an index that disagrees with the files, an unresolved
marker, and a `guarded` lesson whose guard path does not exist. It cannot judge whether a guard
is good; that is review's job, which is why each guarded lesson names a recurrence check.

## Executable recall

Recall used to be prose. It is now a command, so it can be run as the first step of a change:

    python -m scripts.lessons_audit --recall stage 1 retype

It lists every lesson whose title, area, symptom or root cause mentions all the words, with
`open` lessons first (nothing prevents those recurring) and each lesson's recurrence check.
Run the checks it prints and say so in the change.

## Retracting a lesson or a rule

A lesson, or a rule built on one, can be wrong. Do not delete it: write a new lesson that says
what was believed, what the evidence showed and the corrected method. L010 is the example: a
"thin series" rule was committed on the premise that CMCT traded 11 shares a day, a comparison
against FMP's non-split-adjusted endpoint showed it traded about $6M a day because stored volume
is back-adjusted, the rule was removed in its own commit, and the corrected method was recorded.
The ledger shows the mistake and its fix, and the next rule written near that area will find it.

## How this architecture was built and improved

Each step was driven by a failure, and each left a check behind.

| Step | Trigger | What was added |
|---|---|---|
| 1 | Nine incidents in one session lived only in commit messages | The ledger (`docs/etl-lessons/`), the audit (`scripts/lessons_audit.py`), the skill and its design record, routed and inventoried in `SYSTEM.md` |
| 2 | A lesson marked guarded with no guard would be indistinguishable from a real one | The rule that `guarded` needs a guard path that exists, enforced by the audit and its tests |
| 3 | A classifier fix (L008) was parked, then shipped once its blocker was resolved | Status moves from `open` to `guarded` in the same commit as the guard |
| 4 | A merge refusal turned out to be a false alarm (TORO, DSX) | An evidence-required override instead of loosening the check; the evidence is stored with the archive and recorded in L005 |
| 5 | Retyping securities minted new identities for types the repair did not list | L003 widened to "consider every stored type", with a test per type |
| 6 | A new rule rested on a wrong premise (L010) | The retraction rule above, and the recurrence check "compare with the source before writing a rule" |
| 7 | A recovered backtest number was gross and not investable (L011) | A cost model and floor study, and the check "report after-cost Sharpe with sensitivity" |
| 8 | Recall was prose that nobody had to run | `--recall`, with open lessons first |

What the steps share: measure against the real data before shipping, ship the smallest change,
prove the guard fails when the code is broken, and write the lesson in the same change.

## Boundaries

- This records and recalls engineering lessons. It does not change scoring, schema or data,
  and it is not a place for secrets or host paths.
- Business policy (which securities belong in the universe) stays with
  `business-understanding`; the ledger can record that a change needed a decision, not make it.
- The ledger is not a log. History lives in git; the ledger keeps the one-paragraph form.

## Growing it

- Review `open` lessons when touching their area; either guard them or leave them visible.
- When a guarded lesson's guard is removed, the audit fails; update the lesson in the same change.
- Keep each lesson short enough to read before a change, not after the next incident.
