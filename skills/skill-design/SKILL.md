---
name: skill-design
description: "Use when the Clarify gate passes to define a skill's contract, boundaries, inputs, outputs, handoffs, failure modes, tool scope and reference plan. Do not use for unresolved requirements, implementation, or verification."
version: 1
risk: write
owner: quality
entrypoint: none
tools: []
tags: [skill-authoring, quality, security, token-budget]
---

# Skill Design

Turn a passed Clarify record into an implementable contract. Design decides what
the skill owns and how it proves it; it does not write the skill.

## When to use / when not to use

Use when:

- the Clarify gate is `pass` and the Design gate is not;
- changing a skill's trigger, inputs, outputs, handoffs, risk or tools;
- deciding what stays in `SKILL.md` and what moves to on-demand references.

Do not use when:

- the problem, scope or assumptions are unresolved (`skill-clarify`);
- the task is a file-level plan (`skill-plan`), implementation (`skill-code`) or
  verification (`skill-verify`);
- the task changes product policy, scoring logic, ETL or schema.

## Runner

- **Mode:** Manual only. No executable entrypoint.
- **Confirmation:** `risk: write`; this phase edits only the design record.

## Preflight

- [ ] Read `SYSTEM.md`, `docs/skill-lifecycle.md` and the design record.
- [ ] Confirm the Clarify gate is `pass`.
- [ ] `git status --short` reviewed; unrelated edits left alone.
- [ ] Confirm the skill's risk class and least-privilege tool scope.
- [ ] Do not read `.env`; check env names only.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Doc | `docs/skill-lifecycle.md` | yes | Design gate and security/token policy. |
| Doc | `docs/skill-designs/<name>.md` | yes | Clarified record. |
| File | `skills/<name>/SKILL.md` | no | Existing contract, if any. |
| Code | Authoritative code and tests | yes | Link, do not duplicate. |

## Procedure

1. Complete the preflight.
2. Write the trigger and non-trigger boundaries. Name the adjacent skills
   explicitly.
3. Define inputs by kind (table, file, env name, command) and outputs,
   including evidence and audit rows.
4. Define the read/write boundary. A `read` skill cannot mutate; a `write` or
   `heavy` skill names its confirmation and rollback.
5. Define failure modes, stop conditions and handoffs with the owning skill.
6. Declare only the tools the skill needs. Deny by default; explain why each
   tool is in scope.
7. Plan progressive disclosure: what remains in `SKILL.md`, which
   `references/*.md` files are created, and the `Load when:` trigger for each.
8. Budget the context: `SKILL.md` at most 160 lines / 8,000 chars; each
   reference at most 260 lines / 12,000 chars.
9. Name the verification commands and the exact pass condition. Link the
   authoritative code and test rather than copying the rule.
10. Fill the Design section and set the `design` gate row to `pass` with
    evidence. Run:

    ```bash
    python -m scripts.skill_audit --skill <name> --phase design
    ```

    Later-phase `pending` gates are acceptable; any contract, link, security,
    budget or design finding is not.
11. Hand off to `skill-plan`.

## Outputs

- Completed Design section and `design` gate row in the design record.
- No skill, test, code, data or schema changes.

## Verification

Pass when:

- trigger, non-trigger, inputs, outputs, boundary, handoffs, failure modes,
  tools, references and token plan are complete;
- every adjacent capability has a named handoff;
- the tool list resolves and is least-privilege;
- the verification commands and pass conditions are explicit;
- the design links rather than duplicates authoritative rules;
- the gate row is `| design | pass | <evidence> |`.

```bash
python -m scripts.skill_audit --skill <name> --phase design
```

## Failure handling

- Clarify is incomplete: stop and route to `skill-clarify`.
- The design needs a secret, write access or tool outside scope: stop; route to
  `security-compliance` or the owning write skill.
- Two sources disagree: repository code and tests win; link the winner and
  record the documentation fix as a handoff.
- The design cannot fit the token budget: move detail to references now; do not
  defer the split to code.

## Handoffs

- **Unresolved requirements or assumptions:** route to `skill-clarify`.
- **File/test/rollback planning:** route to `skill-plan`.
- **Security, secrets or access:** route to `security-compliance`.
- **Domain rule owned elsewhere:** route to that skill and link its source.

## Stop conditions

- [ ] The Clarify gate is not `pass`.
- [ ] The design requires a secret or an unapproved tool.
- [ ] The design duplicates an authoritative rule instead of linking it.
- [ ] The token budget cannot be met.
- [ ] The request changes product policy, scoring or data code.
- [ ] Unexpected `git status` changes appear in the scoped area.

## Evidence required

- **State:** design-record path and `design` gate row.
- **Findings:** source path for every contract claim.
- **Commands:** audit argv, exit code and output summary.
- **Handoffs:** target skill, reason and evidence attached.

## Source of truth

- `docs/skill-lifecycle.md`
- `docs/skill-designs/_template.md`
- `SYSTEM.md`
- `scripts/skill_audit.py`

## Context budget

- Always load: this file, the lifecycle contract, the design record and the
  specific skill under review.
- Load only the authoritative source needed for the contract.
- Do not load all five lifecycle skills or unrelated references.
