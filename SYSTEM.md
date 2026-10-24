# SYSTEM — Agent Orchestrator

Status: phase 3. The skills and the deterministic executor
(`scripts/agent_runner.py`) exist. Skills without an executable entrypoint are
followed manually; the runner never parses commands out of Markdown.

This file is the global contract for the file-based agent workflow. The design
and rationale live in [docs/file-based-agentic-workflow.md](docs/file-based-agentic-workflow.md).

## Precedence

1. Repository code and tests
2. `SYSTEM.md` (this file)
3. The selected `skills/<name>/SKILL.md`
4. The user request

When any two disagree, the higher item wins. Fix the lower item; do not work
around it.

## Scope

The workflow coordinates the existing CRISP-DM pipeline. It does not add
stages, change scoring, or reimplement `scripts.run_full_etl`. The ML model is
not adopted; `modeling-evaluation` is diagnostic only.

## Orchestrator loop

```text
intake
  -> classify (one primary skill)
  -> load (this file + skills/<name>/SKILL.md)
  -> preflight (git status, env presence, migrate --check)
  -> execute (one command or stage at a time)
  -> verify (the skill's verifier)
  -> record (artifacts/runs/<run-id>/)
  -> escalate (stop and report the next safe action)
```

Stop before execution if the skill is missing, has no `## Verification`
section, or the preflight fails.

## Routing

The routing map is the single source of truth in
[docs/file-based-agentic-workflow.md, section 8](docs/file-based-agentic-workflow.md#8-routing-table).
Do not copy it here. A request that matches no route stops and asks for a
decision.

The skill directory name must equal the frontmatter `name`.

## Available skills

| Skill | Risk | Phase |
|---|---|---|
| `analysis-scoring` | write | 2 |
| `business-understanding` | write | 2 |
| `data-acquisition` | heavy | 2 |
| `data-archiving` | heavy | 2 |
| `data-backup-recovery` | heavy | 2 |
| `data-refresh-operations` | heavy | 2 |
| `data-storage-schema` | write | 2 |
| `data-transformation` | write | 2 |
| `data-understanding` | read | 1 |
| `data-validation` | read | 2 |
| `deployment-release` | heavy | 2 |
| `investment-analysis` | write | 2 |
| `modeling-evaluation` | write | 2 |
| `observability-nightly-verification` | read | 1 |
| `security-compliance` | read | 1 |

All 15 skills exist. Only the skills with a fixed entrypoint can be executed by
the runner; for the rest, apply the skill procedure directly and report the
evidence in the response.

## Hard stops

Stop and report when:

- `git status` shows unexpected edits in a scoped change;
- `python -m scripts.migrate --check` reports pending migrations before a write;
- a stage exits non-zero or a verifier fails;
- a request would write `market.*`, delete reference rows, or release a ticker
  conflict without its dedicated confirmed command;
- `--run-labels` is requested with `--limit` or `--tickers`;
- a secret value would be printed, logged, or committed;
- a command is not in `src/crispdm/ops/catalog.py` when running as a queued task.

## Command policy

- Build argv as a list from fixed module names and validated values. Never
  interpolate request text into a shell string.
- One write stage at a time; respect the `run_full_etl` pipeline lock.
- Read-only skills may inspect the database but must not write.
- Never read or print `.env` values. Check presence only.
- Do not install packages or change dependencies without an explicit request.
- Do not bypass `python -m scripts.migrate --check` before a schema write.

## Verification

A skill is complete only when its verifier passes. Common gates:

```bash
ruff check .
ruff format --check .
python -m pytest -q
python -m pytest -m "not integration" -q
python -m scripts.migrate --check
python -m scripts.check_schema_drift --quiet
```

Use the narrowest gate that proves the change, plus the repository gate for any
code change.

## Run record

Every runner invocation writes:

```text
artifacts/runs/<run-id>/
├── plan.json
├── commands.log
├── verification.json
└── summary.md
```

`artifacts/` is gitignored. A manual run reports the selected skill, commands
run, exit codes, and evidence in the response.
