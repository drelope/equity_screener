---
name: skill-plan
description: "Use when the Design gate passes to map a skill change to exact files, tests, verifier commands, rollback and acceptance evidence. Do not use before design approval, or for implementation and verification."
version: 1
risk: write
owner: quality
entrypoint: none
tools: []
tags: [skill-authoring, quality, security, token-budget]
---

# Skill Plan

Convert an approved skill design into a small, testable change plan. The plan is
the contract for `skill-code`; it contains no implementation.

## When to use / when not to use

Use when:

- the Design gate is `pass` and the Plan gate is not;
- a skill change needs file-level scope, tests and rollback;
- an acceptance criterion needs a proving command.

Do not use when:

- design is incomplete or disputed (`skill-design`);
- the task is editing files (`skill-code`) or running the final gates
  (`skill-verify`);
- the change is to product, data, scoring, schema or deployment code.

## Runner

- **Mode:** Manual only. No executable entrypoint.
- **Confirmation:** `risk: write`; this phase edits only the design record.

## Preflight

- [ ] Read `SYSTEM.md`, `docs/skill-lifecycle.md` and the design record.
- [ ] Confirm the Clarify and Design gates are `pass`.
- [ ] `git status --short` reviewed; unrelated edits are out of scope.
- [ ] Confirm the approved reference and token plan.
- [ ] Do not read `.env`; check env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/skill-lifecycle.md` | yes | Plan gate and acceptance rules. |
| Doc | `docs/skill-designs/<name>.md` | yes | Approved Clarify and Design sections. |
| File | `skills/<name>/SKILL.md` | no | Existing skill, if any. |
| Test | Targeted test files | no | Existing coverage to extend. |

## Procedure

1. Complete the preflight.
2. List every file to add, modify or delete. Use repository-relative paths.
3. List every test to add or change, and the behavior it proves.
4. Name the verifier commands and expected exit codes, including
   `python -m scripts.skill_audit --skill <name> --phase plan`.
5. Map every acceptance criterion from Clarify to a test or command. A criterion
   with no proof is a stop condition.
6. Define rollback: files to restore or remove; no data or schema rollback
   unless the design explicitly owns it.
7. Estimate the token impact. If `SKILL.md` would exceed budget, add the
   reference split to the plan.
8. Review the plan for scope creep. Remove anything not required by the
   acceptance criteria.
9. Fill the Plan section and set the `plan` gate row to `pass` with evidence.
   Later-phase `pending` gates are acceptable.
10. Hand off to `skill-code` with the exact plan.

## Outputs

- Completed Plan section and `plan` gate row.
- No file, test, data or schema changes.

## Verification

Pass when:

- the file list, test list, verifier commands and rollback are complete;
- every acceptance criterion has a proving command or test;
- the plan fits the token budget;
- the gate row is `| plan | pass | <evidence> |`.

```bash
python -m scripts.skill_audit --skill <name> --phase plan
```

## Failure handling

- A criterion has no proof: return to `skill-design` or add the missing test to
  the plan; do not start code.
- The plan grows beyond the approved design: stop and route the extra scope to
  its owner.
- A change needs data or schema writes: stop; this lifecycle does not own them.
- The rollback is undefined: stop; do not start code.

## Handoffs

- **Design gap:** route to `skill-design`.
- **Implementation:** route to `skill-code`.
- **Data, schema or scoring change:** route to the owning domain skill.
- **Security or secret risk:** route to `security-compliance`.

## Stop conditions

- [ ] Clarify or Design is not `pass`.
- [ ] An acceptance criterion has no test or command.
- [ ] The plan includes unrelated or opportunistic edits.
- [ ] The plan requires a data, schema or production write.
- [ ] The token budget is exceeded and no reference split is planned.
- [ ] Unexpected `git status` changes appear in the scoped area.

## Evidence required

- **State:** design-record path and `plan` gate row.
- **Findings:** acceptance criterion → test/command mapping.
- **Commands:** audit argv, exit code and output summary.
- **Handoffs:** target skill, reason and evidence attached.

## Source of truth

- `docs/skill-lifecycle.md`
- `docs/skill-designs/_template.md`
- `SYSTEM.md`
- `scripts/skill_audit.py`

## Context budget

- Always load: this file, the lifecycle contract, the design record and the
  concrete files named by the plan.
- Do not load all five lifecycle skills.
- Do not preload the full test suite; read the targeted tests named in the plan.
