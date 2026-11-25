# Quickstart: P0 Recovery Foundations

## Purpose

This guide validates the P0 recovery scaffolding locally. Passing these commands means the bundle is internally consistent and the local regression suite is green. It does **not** mean approval, promotion, AC closure, or production readiness.

## Prerequisites

- Python 3.11+ with project dependencies installed.
- PostgreSQL available only if running database-gated tests or isolated rehearsals.
- Docker only for disposable rehearsal containers.
- Current branch: `feature/speckit-recovery`.
- Active feature: `specs/001-p0-recovery`.

## 1. Static validation

```bash
ruff check .
ruff format --check .
python3 scripts/check_evidence_closeout.py
python3 scripts/check_migration_candidates.py
python3 scripts/check_reproducibility_locks.py
python3 scripts/check_reproducibility_enforcement.py
```

Expected:

- `ruff` and format checks pass.
- Closeout reports `pass_draft_not_promotion_grade`.
- Candidate checker reports PASS and `NOT approved/applied`.
- Reproducibility lock check passes as scaffolding.
- Enforcement reporter produces a draft gap report with `enforcement_claim=false`.

## 2. Focused checker tests

```bash
PYTHONPATH=. python3 -m pytest \
  tests/test_check_evidence_closeout.py \
  tests/test_check_migration_candidates.py \
  tests/test_check_candidate_backfill_readiness.py \
  tests/test_check_manifest_ledger_policy.py \
  tests/test_check_manifest_ledger_integrity.py \
  tests/test_check_promotion_evidence.py \
  tests/test_check_reproducibility_enforcement.py \
  tests/test_manifest_store.py \
  tests/test_output_store.py \
  tests/test_run_manifest.py \
  tests/test_pit_guards.py \
  -q
```

Expected: all selected tests pass.

## 3. Full local suite

```bash
PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider
```

Expected baseline from this branch: **2,060 passed, 0 failed**. A different result must be investigated before any review-plan decision.

## 4. Policy gates that must fail while unapproved

```bash
python3 scripts/check_manifest_ledger_policy.py --require-approved
python3 scripts/check_promotion_evidence.py \
  --manifest docs/speckit-recovery/08-implementation-validation/promotion-policy-template.json \
  --require-promotion-grade
python3 scripts/check_reproducibility_enforcement.py --require-enforced
```

Expected: all exit non-zero with named gaps. This failure behavior is the safety contract, not a tooling defect.

## 5. Isolated database rehearsal

Only with Docker and a disposable database:

```bash
python3 scripts/rehearse_p0_full.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:<port>/rehearsal' \
  --drafts-dir docs/speckit-recovery/08-implementation-validation/sql-candidates \
  --apply --verify --rollback \
  --i-understand-disposable-target
```

Expected: apply, verification, rollback, and post-rollback verification all pass; `public.schema_migrations` remains intact; container is destroyed afterward.

For synthetic backfill validation:

```bash
python3 scripts/rehearse_backfill_synthetic.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:<port>/rehearsal' \
  --out docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/synthetic-backfill-<date>.json \
  --i-understand-disposable-target
```

Expected: readiness checker reports `checks_passed` for V0107–V0110.

## 6. Optional read-only ledger checks

With an isolated ledger target only:

```bash
python3 scripts/show_run_ledger.py --run-id <run-id> --dsn <isolated-dsn>
python3 scripts/check_manifest_ledger_integrity.py --dsn <isolated-dsn>
```

Expected: found bundle reads successfully; missing run exits 1; corrupted manifests are detected.

## Stop conditions

Stop and record a gate failure if:

- M1 approval evidence is missing from `docs/speckit-recovery/06-execution-prep/m1-decision-log-template.md` or the constitution in `.specify/memory/constitution.md` is not ratified; merge, release, promotion, and cutover remain blocked.
- Any checker that must fail while unapproved returns success.
- Any write command is invoked without explicit acknowledgement flags.
- Shared/production targets are used.
- A database rehearsal leaves candidate objects behind after rollback.
- Promotion or AC closure is claimed from these checks.
