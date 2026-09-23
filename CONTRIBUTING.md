# Contributing — Dividend Equity Screener

The repository runs a single-owner, CI-gated workflow. This file makes the
Release/Change-Management role explicit: every change lands on `main` only
through a branch and a reviewed pull request.

## 1. Branch model

- `main` is the only long-lived branch and is always CI-green
  (`ruff check`, `ruff format --check`, `pytest`).
- Feature work uses short-lived branches named by convention:

  | Prefix | Use | Example |
  |---|---|---|
  | `feat/` | new capability | `feat/label-targets` |
  | `fix/` | defect repair | `fix/etl-indentation` |
  | `docs/` | documentation / SDLC artifacts | `docs/sdlc-review` |
  | `chore/` | tooling, deps, CI | `chore/pin-postgres-digest` |
  | `refactor/` | behavior-preserving change | `refactor/sec-session` |

- Create a branch before editing anything except trivial single-line docs:

  ```bash
  git switch -c feat/label-targets
  ```

## 2. Commit convention

- One logical change per commit; Conventional-Commits style:

  ```text
  <type>(<scope>): <imperative summary>

  <body: what and why, references to docs/issues>
  ```

  Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `security`.
- Never commit `.env`, secrets, or generated artifacts (see `.gitignore`).

## 3. Before you open a PR

```bash
ruff check .          # lint gate
ruff format --check . # format gate
python -m pytest -q   # test gate (local Dockerized Postgres not required; tests are mocked)
python -m scripts.evaluate_walk_forward   # if the change touches the ML layer
```

Then push and open a pull request against `main`. For the single-owner case a
PR is still required so the diff is attributable and reviewable; a second
opinion (even a self-review against the checklist below) is the review step.

## 4. PR checklist

- [ ] Diff is scoped to one concern; `git status` shows only intended files.
- [ ] No secrets or `.env` content in the diff (`git diff --cached | grep -i api_key`).
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `pytest` passes; new behavior has a test.
- [ ] SDLC-sensitive changes touch `docs/sdlc-review.md` or the relevant
      `docs/*.md` artifact (requirements, labeling, runbook).
- [ ] SQL/schema changes add a migration under `sql/migrations/` and a
      schema-comment (`COMMENT ON COLUMN`) entry.
- [ ] README is updated when user-facing commands or the data flow change.

## 5. Branch protection (once the repo is hosted)

When the repo is pushed to a forge (GitHub Actions is already configured), turn
on branch protection for `main`:

- Require pull request reviews before merging.
- Require status checks: `Lint (ruff)` and at least one `Tests (pytest)`.
- Require linear history; disable force-push and direct pushes.

## 6. Releases

- Tag releases with `v<major>.<minor>.<patch>` (e.g. `git tag -a v0.2.0`) on
  `main` when the Azure gate is met (reproducible local MVP + walk-forward
  passing). See `docs/deployment-runbook.md` for the release and rollback
  procedure.