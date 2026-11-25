# Candidate Backfill / Reconciliation Readiness

Status: **candidate-only, not approved, not applied.** These checks are read-only
diagnostics for `V0107`–`V0110`; they do not backfill data, mutate schema, or
constitute promotion evidence.

## Purpose

Promotion needs more than DDL compatibility: the PIT membership, timing,
evidence/quarantine, and manifest-ledger structures must be populated from
approved sources and reconciled. This directory defines the **readiness
gate** that reports whether that backfill exists and whether obvious anomalies
are present.

## Run

Static checks only (no database connection):

```bash
python3 scripts/check_candidate_backfill_readiness.py
```

Read-only checks against an explicit isolated/approved target:

```bash
python3 scripts/check_candidate_backfill_readiness.py \
  --dsn 'postgresql+psycopg://postgres:test@127.0.0.1:55439/rehearsal' \
  --json-out docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/readiness-<date>.json
```

Safety behavior:

- refuses non-local hosts without `--allow-nonlocal`;
- refuses shared/production-like database names without `--allow-shared-name`;
- opens a `READ ONLY` transaction with a statement timeout;
- emits only host/database/driver in the report, never credentials.

Exit codes: `0` = static pass or all checks passed; `1` = schema missing,
backfill incomplete, or anomaly; `2` = safety refusal, DB error, or usage error.

## Check Catalog

The Python module is the canonical catalog. Regenerate the SQL review artifact
after changing checks:

```bash
python3 scripts/check_candidate_backfill_readiness.py --print-sql \
  > docs/speckit-recovery/08-implementation-validation/sql-candidates/backfill/readiness_checks.sql
```

- `V0107` RM-01: membership/eligibility row counts, delisted-date coverage,
  inactive-without-delisted-date, open intervals, overlapping intervals.
- `V0108` RM-02: timing-column coverage, availability before ex-date,
  availability without evidence source, known-at after retrieval, all-NULL
  availability.
- `V0109` RM-03: evidence coverage vs raw dividends, quarantine/correction
  linkage, duplicate source-event groups.
- `V0110` RM-04/05: manifest/output counts, missing manifest hash/JSON,
  outputs without storage reference/content hash.

## Backfill Order and Gates

1. `V0107` membership backfill from an approved membership/listing source;
   reconcile `delisted_date` and interval overlaps. Gate: M1, EX-001, EX-004,
   UNK-003.
2. `V0108` timing backfill from approved provider timestamps/evidence; populate
   `available_at` and `timing_evidence_source`; never invent known-at values.
   Gate: M1, EX-003, UNK-001, UNK-002.
3. `V0109` evidence-first capture/dual-read/cutover; quarantine unresolved
   conflicts and corrections without destructive overwrite. Gate: M1, EX-002,
   UNK-002, UNK-005.
4. `V0110` optional historical manifest/output ledger backfill; new runs should
   persist directly once DEC-002/003/005 define immutability/retention. Gate:
   M1, DEC-002, DEC-003, DEC-005.

No backfill SQL is committed here yet: source mappings, status taxonomy,
adjustment-basis/feed precedence, and cutover rules are approval-gated. The
readiness report tells the operator which gate is still unmet.

## Synthetic Rehearsal (2026-11-16)

`synthetic-backfill-2026-11-16.sql` + `scripts/rehearse_backfill_synthetic.py`
load invented securities, membership/timing, evidence/quarantine/correction, and
one ledger manifest/output on a disposable target. After applying V0107–V0113,
the fixture moved the readiness checker from `not_ready_no_backfill_data` to
`checks_passed` for V0107–V0110. Evidence: `synthetic-backfill-2026-11-16.json`
and `readiness-after-synthetic-synthetic-backfill-2026-11-16.json`. The cutover
sequence is in `synthetic-cutover-dry-run.md`. This is synthetic rehearsal only;
no approval or promotion is implied.

## Promotion Guardrails

- `sql-candidates/` must never be moved into `sql/migrations/` until approvals,
  fresh isolated apply/rollback, and backfill/cutover evidence exist.
- A `checks_passed` report means only that the stated diagnostics passed on that
  target at that time; it is not an AC closure, promotion-grade validation, or
  production-readiness claim.
- Do not run read-only checks against a shared database unless explicitly
  approved; prefer an isolated disposable target with approved/synthetic data.
