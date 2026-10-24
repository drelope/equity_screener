---
name: security-compliance
description: "Use when auditing secret handling, API authentication, SEC user-agent compliance, rate limits or committed-key risk. Do not use to rotate, paste or edit secret values; that is an operator action."
version: 1
risk: read
owner: security
entrypoint: none  # none|fixed|list
tags: []
---

# Security and Compliance

Audit the repository's security boundary and report actionable findings. This
skill never prints, copies, writes or rotates a secret. Configuration changes
are handed to the operator.

## When to use / when not to use

Use when:

- a change touches `.env`, credentials, API auth or SEC access;
- reviewing whether a key or token could be committed;
- checking that the API is closed by default;
- confirming the SEC user agent and rate-limit behavior.

Do not use when:

- a secret must be rotated: the operator follows `docs/deployment-runbook.md`
  section 6;
- a credential must be added to a local `.env`;
- the task is a dependency CVE audit (CI runs `pip-audit`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| File | `.env.example` | yes | Documents required variable names and placeholders. |
| File | `docs/deployment-runbook.md` section 6 | yes | Rotation and storage rules. |
| File | `.gitignore`, `.dockerignore` | yes | Exclusion rules for local secrets. |
| File | `src/crispdm/sec_client.py` | yes | SEC user-agent enforcement. |
| File | `api/main.py` | yes | API key, 503 and rate-limit behavior. |
| Command | `git` | yes | Tracked-file and ignore checks. |
| Command | `python -m pytest` | yes | Behavior verification. |

Variable names in scope: `DATABASE_URL`, `SEC_USER_AGENT`, `API_KEY`,
`OPS_ADMIN_TOKEN`, `OPENBB_PROVIDER`, and the OpenBB credentials file. Never
read or echo their values.

## Procedure

1. Run the preflight from `SYSTEM.md`. Do not print environment values; check
   presence only.
2. Confirm local-only files are not tracked:

   ```bash
   git ls-files .env ObbCredentials.json
   git check-ignore -v .env ObbCredentials.json
   ```

   The first command must print nothing. The second must show the matching
   ignore rule.
3. Confirm placeholders, not real values, are in the committed example:

   ```bash
   git grep -n 'SEC_USER_AGENT\|API_KEY\|OPS_ADMIN_TOKEN' -- .env.example
   ```

4. Confirm the API boundary: `/health` is public; every other route requires
   `X-API-Key`; an unconfigured key returns 503; interactive docs stay off by
   default.
5. Confirm the SEC boundary: placeholder or blank `SEC_USER_AGENT` fails before
   any request, and requests retain the declared user agent and rate limit.
6. Run the targeted tests:

   ```bash
   python -m pytest -q tests/test_api.py
   python -m pytest -q tests/test_walk_forward_checkpoint.py -k sec_session
   ```

7. If the change touches dependencies, note that CI also runs `pip-audit` and
   the gitleaks secret scan.

## Outputs

- No writes.
- A findings report: what was checked, the command, the exit code, and the
  remediation owner.
- A handoff to the operator for any secret rotation or configuration change.

## Verification

Pass when:

- `git ls-files .env ObbCredentials.json` prints nothing;
- both paths are matched by an ignore rule;
- `.env.example` contains placeholders only;
- the API and SEC targeted tests pass;
- no finding contains a secret value.

## Failure handling

- Tracked secret found: stop. Do not print the value. Report the path and
  variable name, rotate per `docs/deployment-runbook.md` section 6, and get
  explicit approval before any history rewrite.
- Placeholder SEC user agent in a live environment: stop; no SEC request may
  run until a real contact string is configured.
- API key unset in a deployment that expects auth: report the 503 behavior; do
  not weaken auth to make a client work.
- A test needs a real credential: skip it and report; never fabricate one.

## Source of truth

- `docs/deployment-runbook.md` section 6
- `.env.example`
- `src/crispdm/sec_client.py`
- `api/main.py`
- `.github/workflows/ci.yml`

## Runner

- **Mode:** Follow this skill's procedure. The deterministic runner only executes allowlisted fixed entrypoints; most work here is manual unless stated otherwise.
- **Confirmation:** Skills with `risk: write` or `risk: heavy` require `--yes` when executed via the runner. Never parse commands from Markdown.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches the database or schema.
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No pipeline lock held / no conflicting run in progress if executing `run_full_etl`.
- [ ] Scope narrowed to the smallest change that satisfies the request.

## Handoffs

- **DB/schema drift:** route to `data-storage-schema` with `migrate --check` output and affected tables.
- **Missing/dirty source data:** route to `data-acquisition` with coverage gaps and tables.
- **Freshness/health check:** route to `observability-nightly-verification` with `audit.nightly_runs`/`audit.nightly_checks`.
- **Security/secret risk:** route to `security-compliance` (do not share secret values).
- **Investment validation, KPI/risk interpretation or a report:** route to `financial-analysis`.
- **Scoring/labeling policy:** route to `financial-scoring` or `modeling-evaluation` per boundaries above.

## Stop conditions

- [ ] Task is outside this skill's scope (see "Do not use when").
- [ ] `python -m scripts.migrate --check` reports pending migrations before a write operation.
- [ ] `--run-labels` requested with `--limit` or `--tickers` (partial runs must not be labeled).
- [ ] Action would delete reference rows, prune historical features/returns outside the allowed command, or release a ticker conflict without its dedicated confirmed command.
- [ ] Secret would be printed, logged, or committed.
- [ ] Non-zero exit from a required command with no documented "finding" handling.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** affected tables/rows, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger state, or files written.
- **Findings:** relation/filter/as-of for quantitative claims; diffs for schema/config changes.
- **Handoffs:** target skill + reason + evidence attached.
