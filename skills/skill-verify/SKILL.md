---
name: skill-verify
description: "Use when the Code gate passes to run the deterministic skill audit, targeted tests, ruff and runner smoke checks, and to record the final evidence. Do not use before code is complete or to implement fixes silently."
version: 1
risk: read
owner: quality
entrypoint: fixed
tools: []
tags: [skill-authoring, quality, security, token-budget]
---

# Skill Verify

Run the final gates for a skill change. Verification reports evidence; it does
not quietly repair the change.

## When to use / when not to use

Use when:

- the Code gate is `pass` and the Verify gate is not;
- a skill change needs the final audit and test evidence;
- a previous verification failed and the code has been corrected.

Do not use when:

- any earlier gate is not `pass`;
- the task is implementation (`skill-code`) or planning (`skill-plan`);
- the task is a domain change outside skill authoring.

## Runner

- **Mode:** Fixed entrypoint. The deterministic runner executes only
  `python -m scripts.skill_audit --all`; it never parses commands from Markdown.
- **Confirmation:** `risk: read`, so no `--yes` is required. The runner executes
  the audit only.

## Preflight

- [ ] Read `SYSTEM.md`, `docs/skill-lifecycle.md` and the design record.
- [ ] Confirm the Clarify, Design, Plan and Code gates are `pass`.
- [ ] `git status --short` reviewed; unrelated edits are not verified.
- [ ] Confirm the targeted test list and the design-record token budget.
- [ ] Do not read `.env`; check env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/skill-lifecycle.md` | yes | Final gate and evidence rules. |
| Doc | `docs/skill-designs/<name>.md` | yes | Four passed gates and Code evidence. |
| File | `skills/<name>/SKILL.md` | yes | Implemented contract. |
| File | `skills/<name>/references/*.md` | no | On-demand references. |
| Test | Targeted tests from the plan | yes | Must pass unchanged. |

## Procedure

1. Complete the preflight.
2. Run the deterministic repository gate:

   ```bash
   python -m scripts.skill_audit --all
   ```

3. Run the runner smoke checks:

   ```bash
   python -m scripts.agent_runner --list
   python -m scripts.agent_runner --skill skill-verify --dry-run
   python -m scripts.agent_runner --skill skill-verify
   ```

4. Run the targeted tests, then the repository style gates:

   ```bash
   python -m pytest -q <targeted tests>
   ruff check .
   ruff format --check .
   git diff --check
   ```

5. Confirm the scoped diff contains only planned files. Stop on an unexpected
   edit, a secret or an absolute host path.
6. Fill the Verify section and set the `verify` gate row to `pass` with the
   command evidence. This is evidence recording only; do not change skill or
   code behavior during verification.
7. Re-run `python -m scripts.skill_audit --all` after the gate row is written.
8. Report the skill, run id, commands, exit codes, evidence paths and any
   residual risk.

## Outputs

- Verification evidence in the response and the design record.
- A passing `verify` gate row.
- No silent code, test or data changes.

## Verification

Pass when:

- `python -m scripts.skill_audit --all` exits `0`;
- the runner lists the skill, its dry run resolves no tools, and the fixed audit
  run passes;
- targeted tests pass;
- `ruff check .` and `ruff format --check .` pass;
- `git diff --check` is clean;
- the scoped diff contains only planned files;
- the gate row is `| verify | pass | <evidence> |`;
- the final `skill_audit --all` still exits `0`.

```bash
python -m scripts.skill_audit --all
```

## Failure handling

- Audit failure: report the exact finding and route the fix to `skill-code`;
  do not edit during verification.
- Test failure: report the failing test and expected behavior; route to
  `skill-code` or `skill-design` if the contract is wrong.
- Ruff failure: report it; fix only as a planned code change, then re-verify.
- Unexpected diff or secret: stop; do not mark the gate.
- A gate is missing or not `pass`: stop; verification cannot skip a phase.

## Handoffs

- **Implementation or test fix:** route to `skill-code`.
- **Contract or design defect:** route to `skill-design`.
- **Plan gap:** route to `skill-plan`.
- **Secret, auth or access finding:** route to `security-compliance`.
- **Domain change found during verification:** route to the owning domain skill.

## Stop conditions

- [ ] An earlier gate is not `pass`.
- [ ] `python -m scripts.skill_audit --all` exits non-zero.
- [ ] A targeted test, ruff or `git diff --check` fails.
- [ ] The diff contains an unplanned or unrelated file.
- [ ] A secret or absolute host path is present.
- [ ] The design record still contains `pending` or `fail` rows.

## Evidence required

- **Commands:** argv, cwd, exit codes and timestamps.
- **State:** design-record path, five gate rows and affected files.
- **Findings/handoffs:** audit output, test summary, ruff result and target skill with evidence.

## Source of truth

- `docs/skill-lifecycle.md`
- `docs/skill-designs/_template.md`
- `SYSTEM.md`
- `scripts/skill_audit.py`
- `scripts/agent_runner.py`

## Context budget

- Always load: this file, the lifecycle contract, the design record and the
  targeted tests; run the audit instead of reading every skill by hand.
- Do not load all five lifecycle skills or unrelated domain skills.
