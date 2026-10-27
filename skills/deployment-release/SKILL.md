---
name: deployment-release
description: "Use when releasing, deploying, rebuilding the image, or rolling back the local Compose stack. Do not use for schema-only migrations or for nightly ETL execution."
version: 1
risk: heavy
owner: operations
entrypoint: none  # none|fixed|list
tags: []
---

# Deployment and Release

Release the local-first stack safely: CI green, image rebuilt, migrations
applied once, health verified, and a rollback path known before starting.

## When to use / when not to use

Use when:

- cutting a release tag;
- deploying or rebuilding the Compose services;
- rolling back to a previous tag or image digest;
- changing `Dockerfile`, `docker-compose.yml` or the CI workflow.

Do not use when:

- the task is only a migration (`data-storage-schema`);
- the task is a nightly run (`data-refresh-operations`);
- the task is a database restore (`data-backup-recovery`).

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `API_KEY` | yes | Required by every `docker compose` command. |
| Env | `POSTGRES_PASSWORD` | yes | Never print the value. |
| Env | `OPS_ADMIN_TOKEN`, `SEC_USER_AGENT` | yes for the app/worker | Presence only. |
| File | `Dockerfile`, `docker-compose.yml` | yes | Build and service definitions. |
| File | `.github/workflows/ci.yml` | yes | Lint, test, dependency and secret gates. |
| Doc | `docs/deployment-runbook.md` | yes | Release, rollback, secrets, schedule. |
| Doc | `CONTRIBUTING.md` | yes | Branch and PR model. |

## Procedure

1. Run the preflight from `SYSTEM.md`. Confirm a clean scoped diff and that
   `API_KEY` is exported for Compose.
2. Land a PR that is CI-green (`ruff`, `pytest`, `pip-audit`, gitleaks).
3. Before deploying a risky change, take a backup (`data-backup-recovery`) and
   confirm the previous release tag/digest.
4. Tag after merge:

   ```bash
   git tag -a v0.X.0 -m "v0.X.0"
   git push origin v0.X.0
   ```

5. Deploy locally:

   ```bash
   docker compose pull
   docker compose up -d postgres
   docker compose up migrate
   docker compose up -d api streamlit worker
   ```

   Rebuild after a code change; a running container keeps its image:

   ```bash
   docker compose build
   docker compose up -d
   ```

6. Sanity check:

   ```bash
   curl -s localhost:8000/health
   curl -s -H "X-API-Key: $API_KEY" localhost:8000/metrics/enriched/AAPL
   ```

7. Run the morning verification after the next nightly (or on demand):

   ```bash
   python -m scripts.verify_nightly_run
   ```

## Outputs

- A release tag.
- Rebuilt/restarted Compose services.
- A migration ledger at the target version.
- Deployment evidence from the health, metrics and verifier checks.

## Verification

Pass when:

- CI is green before the tag;
- `docker compose up migrate` completes and `scripts.migrate --check` exits 0;
- `/health` returns success and an authenticated route returns data;
- `scripts.verify_nightly_run` reports the expected state;
- the running image matches the intended build (check `/app` inside the
  container, not the host checkout).

## Failure handling

- CI red: do not tag or deploy.
- Migration failure: stop; migrations are forward-only. Fix forward or restore
  the pre-migration dump, then re-run.
- API crash-loop on OpenBB `PermissionError`: rebuild the image; OpenBB's build
  must happen in the Dockerfile, not at runtime.
- `ObbCredentials.json` absent: Compose mounts a directory in its place and
  provider calls fail; restore the host file and restart.
- Rollback: previous tag/digest, `postgres`, `migrate`, then services. Use
  `docker compose down -v` only as a last resort after a backup.
- Do not pin a mutable tag when a digest is available.

## Source of truth

- `docs/deployment-runbook.md`
- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/ci.yml`
- `CONTRIBUTING.md`
- `scripts/verify_nightly_run.py`

## Runner

- **Mode:** Follow this skill's procedure. The deterministic runner only executes allowlisted fixed entrypoints; most work here is manual unless stated otherwise.
- **Confirmation:** Skills with `risk: write` or `risk: heavy` require `--yes` when executed via the runner. Never parse commands from Markdown.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.

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
- [ ] Secret would be printed, logged or committed, or a required command fails without documented "finding" handling.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** affected tables/rows, `audit.nightly_runs`/`audit.nightly_checks`, migration ledger state, or files written.
- **Findings:** relation/filter/as-of for quantitative claims; diffs for schema/config changes.
- **Handoffs:** target skill + reason + evidence attached.
