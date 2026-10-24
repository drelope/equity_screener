---
name: _template
description: "Use when ... Do not use when ..."
version: 1
risk: read  # read|write|heavy
owner: unassigned
entrypoint: none  # none|fixed|list
tools: []  # optional: Python tool names only when skill demands them
tags: []
---

# Skill title

One sentence stating the capability and its boundary.

## When to use / when not to use

Use when:

- concrete trigger;
- concrete trigger.

Do not use when:

- adjacent task that belongs to another skill;
- task that requires a write or a secret.

## Runner

- **Mode:** Manual only (do not guess argv). If `entrypoint: fixed`, the deterministic runner may execute only the allowlisted commands. Never parse commands from Markdown.
- **Confirmation:** `write`/`heavy` skills require `--yes` when run via the executor.

## Preflight

- [ ] Read `SYSTEM.md` and confirm the selected skill is allowed.
- [ ] `git status --short` clean for scoped change (or list exceptions).
- [ ] `python -m scripts.migrate --check` exits 0 (if touching DB/schema/data writes).
- [ ] Required env vars present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No other run holds the pipeline lock (if running `run_full_etl`).
- [ ] Confirm scope (narrowest) and no partial-run label risk.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `schema.table` | yes | Read-only unless `risk` is `write`. |
| File | `path/to/file` | no | Source of truth to link, not copy. |

## Procedure

1. Complete the preflight checklist.
2. Execute one command at a time, in this order:

   ```bash
   python -m scripts.<module>
   ```

3. Stop immediately on a non-zero exit unless the skill documents that exit code as a finding.

## Outputs

- tables written, or `none (read-only)`;
- artifacts written under `artifacts/runs/<run-id>/`, or `none`;
- audit rows written, or `none`.

## Verification

**Pass if:**
- [ ] Exact commands run with exit codes recorded.
- [ ] Evidence collected: table rows / `audit.*` rows / files created / migration ledger state.
- [ ] Targeted tests pass (if code changed).
- [ ] No secrets printed/logged.

```bash
python -m pytest -q tests/test_example.py
```

## Failure handling

- Missing prerequisite: stop and name the command that creates it.
- Partial write: report what was written; do not retry a destructive step blindly.
- Unexpected data: stop and present the evidence.

## Handoffs

- If outside scope → escalate to the owning skill with evidence (commands, errors, paths).
- If DB/schema issue → `data-storage-schema` (include `migrate --check` output).
- If acquisition needed → `data-acquisition` (include missing tables/coverage).
- If verification/health → `observability-nightly-verification`.
- If security/secret risk → `security-compliance` (do not share values).

## Stop conditions

- [ ] Unexpected `git status` changes in scoped area.
- [ ] `python -m scripts.migrate --check` reports pending migrations before a write.
- [ ] A stage exits non-zero or verifier fails.
- [ ] Action would write `market.*`, delete reference rows, or release a ticker conflict without its dedicated confirmed command.
- [ ] `--run-labels` requested with `--limit` or `--tickers`.
- [ ] Secret would be printed/logged/committed.
- [ ] Command not allowlisted for queued tasks.

## Evidence required

- Commands run (argv list), cwd, exit codes, timestamps.
- Evidence paths: affected tables, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger, files.
- Findings with relation/filter/as-of for quantitative claims.
- Routed handoffs with reasons.

## Source of truth

- `path/to/code.py`
- `path/to/document.md`
