---
name: skill-code
description: "Use when the Plan gate passes to implement exactly the approved skill changes, including tests and on-demand references, without scope creep. Do not use without an approved plan, or for final verification."
version: 1
risk: write
owner: quality
entrypoint: none
tools: []
tags: [skill-authoring, quality, security, token-budget]
---

# Skill Code

Implement the approved plan. Code is a bounded execution step; it does not
re-decide scope, design or acceptance.

## When to use / when not to use

Use when:

- the Clarify, Design and Plan gates are `pass`;
- the plan names every file, test, verifier and rollback;
- the change is confined to skills, their tests and their documentation.

Do not use when:

- any earlier gate is `pending` or `fail`;
- the task is requirements, design or planning;
- the task is final verification (`skill-verify`);
- the change touches scoring, ETL, schema, UI or deployment code.

## Runner

- **Mode:** Manual only. No executable entrypoint.
- **Confirmation:** `risk: write`; change only the files approved in the plan.

## Preflight

- [ ] Read `SYSTEM.md`, `docs/skill-lifecycle.md` and the design record.
- [ ] Confirm Clarify, Design and Plan gates are `pass`.
- [ ] `git status --short` reviewed; record unrelated edits and leave them.
- [ ] Confirm the planned file list and tests.
- [ ] Do not read `.env`; check env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/skill-designs/<name>.md` | yes | Approved plan and acceptance mapping. |
| File | `skills/<name>/SKILL.md` | no | Existing skill, if any. |
| File | `skills/<name>/references/*.md` | no | Planned on-demand references. |
| Test | Targeted tests from the plan | yes | Extend, do not weaken. |

## Procedure

1. Complete the preflight.
2. Add or update the tests named in the plan first.
3. Implement the smallest change that satisfies the plan. Keep the required
   skill sections and frontmatter contract.
4. Create each planned reference with a one-line `Load when:` trigger and link
   it from `SKILL.md`.
5. Keep secrets and environment values by name only. Never read or print a
   secret.
6. Run the targeted tests and `python -m scripts.skill_audit --skill <name>
   --phase code`. Later-phase `pending` gates are acceptable; every other
   finding is not.
7. Update the Code section and set the `code` gate row to `pass` with evidence.
8. Report the actual files changed. If a deviation from the plan was required,
   record it and stop for plan re-approval before continuing.
9. Hand off to `skill-verify`.

## Outputs

- The planned skill, reference, test and documentation changes.
- Completed Code section and `code` gate row.
- No unrelated edits.

## Verification

Pass when:

- only planned files changed;
- tests cover the planned behavior and pass;
- `SKILL.md` and every reference are within the token budget;
- every reference has a `Load when:` trigger and is linked;
- the audit reports no finding through the Code phase;
- the gate row is `| code | pass | <evidence> |`.

```bash
python -m scripts.skill_audit --skill <name> --phase code
python -m pytest -q <targeted tests>
```

## Failure handling

- A test exposes a design gap: stop and return to `skill-design`; do not patch
  around it.
- The plan is incomplete: stop and return to `skill-plan`.
- The change needs a secret, data write or schema change: stop; it is out of
  scope.
- A token budget is exceeded: move detail to a planned reference; do not raise
  the budget silently.
- Unexpected files appear in the diff: stop; revert the unrelated edit.

## Handoffs

- **Design defect:** route to `skill-design`.
- **Plan defect:** route to `skill-plan`.
- **Final verification:** route to `skill-verify`.
- **Security or secret risk:** route to `security-compliance`.
- **Domain change:** route to the owning domain skill.

## Stop conditions

- [ ] An earlier gate is not `pass`.
- [ ] A required test fails.
- [ ] A file outside the plan changes.
- [ ] A secret would be read, printed or committed.
- [ ] The change needs a data or schema write.
- [ ] A token budget is exceeded without an approved reference split.

## Evidence required

- **State:** design-record path and `code` gate row.
- **Findings:** files changed, tests added and their pass/fail output.
- **Commands:** audit and pytest argv, exit codes and output summary.
- **Handoffs:** target skill, reason and evidence attached.

## Source of truth

- `docs/skill-lifecycle.md`
- `docs/skill-designs/<name>.md`
- `SYSTEM.md`
- `scripts/skill_audit.py`

## Context budget

- Always load: this file, the approved plan, the target skill and the targeted
  tests.
- Create references rather than growing `SKILL.md` past 8,000 characters.
- Do not load all five lifecycle skills or unrelated domain skills.
