---
name: skill-clarify
description: "Use when starting a new skill or a material change to an existing skill and the problem, audience, scope, assumptions and success criteria are not yet settled. Do not use for product requirements, data or scoring policy, implementation, or verification."
version: 1
risk: write
owner: quality
entrypoint: none
tools: []
tags: [skill-authoring, quality, security, token-budget]
---

# Skill Clarify

Produce the Clarify gate for a skill change. Clarify records the problem and the
evidence; it does not design, plan or implement.

## When to use / when not to use

Use when:

- creating a skill under `skills/`;
- materially changing a skill's trigger, boundary, inputs, outputs or risk;
- a previous design record has an unresolved question or unvalidated assumption.

Do not use when:

- the problem and scope are already recorded and the Clarify gate is `pass`;
- the task is product scope, scoring policy or acceptance criteria
  (`business-understanding`);
- the task is design, planning, code or verification (the later lifecycle
  skills);
- the change is to data, ETL, schema, UI or deployment code.

## Runner

- **Mode:** Manual only. There is no executable entrypoint; never guess argv.
- **Confirmation:** `risk: write`; this phase edits only the design record.

## Preflight

- [ ] Read `SYSTEM.md` and `docs/skill-lifecycle.md`.
- [ ] `git status --short` reviewed; list unrelated edits and leave them alone.
- [ ] Confirm the skill name is kebab-case and the target design record path.
- [ ] Confirm the request is skill authoring, not a domain change.
- [ ] Do not read `.env`; check required env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/skill-lifecycle.md` | yes | Phase contract and gate owners. |
| Doc | `docs/skill-designs/_template.md` | yes | Design record structure. |
| File | `skills/<name>/SKILL.md` | no | Existing skill, if any. |
| File | `docs/skill-designs/<name>.md` | no | Existing record, if any. |
| Evidence | Repository code, tests and docs | yes | Cite paths; do not assume. |

## Procedure

1. Complete the preflight.
2. Restate the problem and the decision the skill supports in two or three
   sentences.
3. Name the audience and what they must decide or produce.
4. List in-scope and out-of-scope work. Name the owning skill for anything out
   of scope.
5. Collect evidence from code, tests and docs. Record exact paths and what each
   proves. Mark anything not verified as an assumption.
6. Resolve each assumption with evidence or an explicit accepted risk (owner,
   date, consequence). Never leave an open question.
7. Define measurable success criteria and the command or test that proves each.
8. Set the risk class, least-privilege tool list and token budget.
9. Create or update `docs/skill-designs/<name>.md` from the template. Fill the
   Clarify section and set the `clarify` gate row to `pass` with evidence.
10. If the skill file already exists, run:

    ```bash
    python -m scripts.skill_audit --skill <name> --phase clarify
    ```

    The only acceptable findings are later-phase gates that are still
    `pending`. Stop on any contract, link, security, budget or clarify finding.
11. Hand off to `skill-design`. Do not edit `SKILL.md`, tests or code.

## Outputs

- `docs/skill-designs/<name>.md` with a complete Clarify section and the
  `clarify` gate row.
- No skill, code, data or schema changes.

## Verification

Pass when:

- every Clarify prompt in `docs/skill-lifecycle.md` is answered;
- assumptions have validation evidence or an accepted risk with owner and date;
- success criteria map to commands or tests;
- `Open questions: none` is present;
- the gate row is `| clarify | pass | <evidence> |`;
- `python -m scripts.skill_audit --skill <name> --phase clarify` reports no
  finding for the Clarify gate (run after the skill scaffold exists).

```bash
grep -nE "^## Clarify|Open questions: none|^\| clarify \| pass \|" docs/skill-designs/<name>.md
```

## Failure handling

- Missing evidence: record the gap and stop; do not invent a source.
- Scope overlaps another skill: route to that skill's owner and stop.
- An assumption cannot be validated: record it as an accepted risk with owner,
  date and consequence, or stop.
- The request is a product or policy change: route to
  `business-understanding`.

## Handoffs

- **Design or contract work:** route to `skill-design`.
- **Product scope, weights or acceptance policy:** route to
  `business-understanding`.
- **Secrets, auth or access risk:** route to `security-compliance`.
- **Adjacent data, scoring or deployment work:** route to the owning skill.

## Stop conditions

- [ ] The request is outside skill authoring.
- [ ] A core assumption has no evidence and no accepted owner.
- [ ] The design record exceeds its token budget.
- [ ] A secret or `.env` value would be read, printed or written.
- [ ] Unexpected `git status` changes appear in the scoped area.
- [ ] A later lifecycle phase is being started early.

## Evidence required

- **State:** design-record path and gate row.
- **Findings:** evidence path for each claim; assumption owner/date for accepted
  risks.
- **Commands:** audit command, argv, exit code and output summary.
- **Handoffs:** target skill, reason and evidence attached.

## Source of truth

- `docs/skill-lifecycle.md`
- `docs/skill-designs/_template.md`
- `SYSTEM.md`
- `scripts/skill_audit.py`

## Context budget

- Always load: this file, `docs/skill-lifecycle.md`, the design record and the
  specific skill under review.
- Do not load all five lifecycle skills. One phase skill at a time.
- Do not preload unrelated domain skills; follow a handoff only when it is the
  next action.
