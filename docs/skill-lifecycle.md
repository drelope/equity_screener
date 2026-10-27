# Skill Lifecycle

This document is the shared contract for changing anything under `skills/`.
It turns the five-step engineering lifecycle into five routed skills:
`skill-clarify`, `skill-design`, `skill-plan`, `skill-code`, `skill-verify`.

The lifecycle is deliberately **fail-closed**. A phase is complete only when its
row in the design record is `pass` and its evidence exists. The deterministic
gate is `scripts/skill_audit.py`; the final gate is `skill-verify`.

Scope: authoring and amending skills. Product, data, scoring, deployment and
security work stays with the owning domain skill. This lifecycle does not grant
permission to change those areas.

## Gate owners

| Phase | Primary owner | Also required | Exit artifact |
|---|---|---|---|
| Clarify | Product Owner / Business Analyst | Security | Scope, audience, assumptions, success criteria |
| Design | Architecture / DBA | Security, Data Engineering | Contract, boundaries, tools, failure modes, token plan |
| Plan | Project Manager / Change Management | QA | File/test/rollback plan with acceptance mapping |
| Code | Development / Data Engineering | Technical Writer | Approved changes only |
| Verify | QA / Test Engineering | Security, Release | Commands, exit codes, audit result, evidence |

The roles are the ones defined in [sdlc-review.md](sdlc-review.md). In a
single-owner repository the same person may wear several hats, but the gates do
not collapse.

## Design record

Every lifecycle-managed skill has one durable
`docs/skill-designs/<skill>.md` record, created from
[the template](skill-designs/_template.md). It contains:

- status, owner, risk, source of truth and token budget;
- Clarify, Design, Plan, Code and Verify sections;
- `Open questions: none` — every question is either answered or explicitly
  accepted with its owner and date;
- a five-row gate log, in phase order, with evidence.

A gate log row is `pass`, `pending` or `fail`. The skill audit requires every
row through the requested phase to be `pass`; the final audit requires all five.
An accepted risk is written in the Design section, not left as an open question.
`TODO`, `FIXME` and `TBD:` are rejected in a design record.

## Phase 1 — Clarify

Answer, from repository evidence rather than assumption:

1. What decision or capability does the skill support?
2. Who uses it, and what do they need to decide or produce?
3. What is in scope and explicitly out of scope?
4. Which existing rule, code path or document is authoritative?
5. What is assumed? For each assumption, what validates it?
6. How will success be measured, and by which command or test?
7. What is the risk class (`read`, `write`, `heavy`), and which tools may the
   skill load?
8. What is the token budget?

Do not design or code while any answer is missing. Route product policy to
`business-understanding`, security to `security-compliance`, and an adjacent
capability to its owning skill.

## Phase 2 — Design

Define the contract before implementation:

- trigger and non-trigger boundaries;
- inputs (tables, files, env names, commands), outputs and evidence;
- read/write boundary and handoffs;
- failure modes and stop conditions;
- least-privilege tool scope, deny by default;
- the reference plan: what stays in `SKILL.md`, what moves to
  `references/*.md`, and the `Load when:` trigger for each reference;
- the verification commands and the exact pass condition;
- the source-of-truth links, without copying the rule into two places.

A design that duplicates a rule already owned by code is rejected. Link the
code and test the link.

## Phase 3 — Plan

The plan names:

- every file to add, modify or delete;
- every test to add or change;
- the verifier commands and expected exit codes;
- rollback;
- a mapping from each acceptance criterion to a test or command.

No production or skill edit starts before this mapping exists.

## Phase 4 — Code

Implement only the approved plan.

- One concern per change; no opportunistic edits.
- Do not change scoring, ETL, schema, UI or dependencies unless the design
  explicitly owns that change.
- Write executable truth first: tests, then the smallest implementation.
- Add an on-demand reference instead of growing `SKILL.md` past its budget.
- Keep secrets by name only; never read, print or commit a secret value.

## Phase 5 — Verify

Run, in order:

```bash
python -m scripts.skill_audit --skill <name> --phase verify
python -m scripts.skill_audit --all
python -m scripts.agent_runner --skill skill-verify --dry-run
python -m scripts.agent_runner --skill skill-verify
ruff check .
ruff format --check .
python -m pytest -q <targeted tests>
git diff --check
```

Record the commands, exit codes, affected files and the audit result in the
design record and in the response. A failed gate is a finding, not a reason to
lower the gate.

## Quality gates

The deterministic audit fails on:

- invalid frontmatter, name/directory mismatch or a missing required section;
- a description without both a `Use when` trigger and a `Do not use` boundary;
- broken relative links or source-of-truth paths that do not exist;
- a handoff to an unknown skill;
- read skills declaring mutating tools, or unknown/out-of-scope tools;
- unresolved markers or missing `Open questions: none` in a design record;
- a missing phase or a gate row that is not `pass` through the requested phase;
- routing or `SYSTEM.md` inventory drift.

## Security gates

- No secret values, private-key blocks or absolute host paths.
- Environment variables are named only; `.env` is never read.
- Read skills cannot mutate; writes are handed to a `write` skill with the
  documented confirmation.
- Tools are deny-by-default and resolved from the declared list.
- Skills are instructions, not a shell: never interpolate request text into a
  command string and never execute an unreviewed external script.
- Security-sensitive changes hand off to `security-compliance` before Verify.

## Token gates

- `SKILL.md`: at most **160 lines / 8,000 characters**.
- Each `references/*.md`: at most **260 lines / 12,000 characters**, and it
  must begin with a `Load when:` trigger.
- A design record: at most **220 lines / 12,000 characters**.
- Load one phase skill at a time; do not load all five.
- Load only the reference the current question needs. Do not preload every KPI,
  formula or dashboard table.
- Prefer a link to the authoritative code/doc over a second copy of the rule.

Estimated tokens are reported as `characters / 4`; the limits are deliberately
conservative because they are a context-budget guard, not a model tokenizer.

## Stop conditions

Stop and report instead of proceeding when:

- a prerequisite phase gate is not `pass`;
- a clarification assumption has no validation and no accepted owner;
- the requested change is outside skill authoring;
- the change would touch secrets, `market.*`, reference rows or production data;
- a required test or audit fails;
- the working tree contains unrelated edits in the scoped change;
- a token budget would be exceeded by adding more prose to `SKILL.md`.

## Evidence

Keep:

- the design record with the gate log;
- audit output and exit code;
- targeted test output;
- ruff result;
- the file list and a short diff summary.

Do not claim a phase passed because the prose sounds complete. The evidence is
the command output and the gate row.
