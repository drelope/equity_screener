# Validation Plan (P0, RM-01..07)

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Scope | `AC-P0-01..11`, `QG-01..07`, FR/NFR linked to `RM-01..07` |
| Constraint | No shared/production DB writes for destructive/experimental tests; use isolated disposable DB/schema with rollback/teardown. Capture evidence for every claim. |

## 1. Environment and execution modes

| Mode | Purpose | Requirements |
|---|---|---|
| Unit | Pure logic (dedupe precedence, COALESCE/date preservation, as-of filters, manifest hashing) | Local/CI Python env, no external writes |
| Isolated DB/integration | SQL constraints, migrations, upsert behavior, loader batching, PIT queries | Disposable Postgres/schema or transaction rollback; apply migrations under test; never shared DB |
| End-to-end/read-only UI | Reports Center provenance/as-of rendering and download metadata | Running non-prod app pointed at safe/read-only data; manual/browser evidence for SPA |
| Controlled recompute | PIT universe/adjustment/backtest/eval verification | Approved environment, manifests, frozen inputs/policy; record outputs/hashes |

## 2. Acceptance criteria matrix

| AC | RM/TSK | Validation | Expected evidence |
|---|---|---|---|
| AC-P0-01 | RM-01, TSK-016 | Fixed `as_of` returns identical PIT-eligible universe across reruns/current-state changes | Automated test + manifest/hash comparison |
| AC-P0-02 | RM-01, TSK-017 | PIT recomputes reproduce historical universe/scores from PIT inputs | Controlled recompute log, diff report |
| AC-P0-03 | RM-02, TSK-014 | No feature/signal uses data with `available_at > as_of`; filing/availability timing enforced | Leak regression tests, golden late/amended filing cases |
| AC-P0-04 | RM-03, TSK-018/021 | Adjusted series/total-return correct for split/dividend cases; basis documented | Golden split/dividend cases, continuity checks, sample reconciliation |
| AC-P0-05 | RM-03, TSK-019/020 | Deterministic batch dedupe; NULL incoming does not overwrite existing non-NULL dates unless audited correction; feed evidence retained | Isolated DB tests incl. actual `DIVIDEND_UPSERT`/loader path; audit records |
| AC-P0-06 | RM-03, TSK-018 | Ex-dividend/adjustment outputs carry basis/caveat labels until fully verified where required | UI/API/report assertions, manifest fields |
| AC-P0-07 | RM-04, TSK-008/010 | Material runs produce immutable manifests with required fields and input/output refs | Integration tests, manifest schema validation |
| AC-P0-08 | RM-05, TSK-011/022/023 | Scores/reports/AI outputs run-keyed/non-overwriting in audit contexts; Reports Center shows `resolved_as_of`/`generated_at` and provenance | DB/API/UI tests, `unk004-ui-verification-checklist` evidence |
| AC-P0-09 | RM-06, TSK-026 | Locked reproducible install/build in local/CI/Docker; lock/env captured | CI logs, container build/install proof, manifest fields |
| AC-P0-10 | RM-07, TSK-002/003 | Frozen holdout, versioned acceptance policy, cost/exposure-matched benchmark enforced for promotion-grade claims | Config/policy artifacts, evaluation run manifests, gate tests |
| AC-P0-11 | RM-01..07 | Leakage/adjustment/batch/manifest/report regression suite passes in CI | CI run URL/log, test report artifact |

## 3. Key test cases (minimum)

### PIT/leakage
- Same `as_of` before/after later status change yields same universe.
- Delisted/inactive security eligible only when PIT-valid.
- Late-filed/amended fundamental unavailable before `available_at`.
- Dividend known-as-of respects declaration/filing availability rules.

### Adjustments/dividends
- Split continuity around effective dates for canonical series (RPT/BCHT-like cases + broader sample).
- Multi-values same-key batch does not fail and produces deterministic winner by approved precedence.
- Existing non-NULL declaration/record/payment survives NULL incoming update.
- Different feed/provider evidence retained (no silent destructive supersession).
- Implausible/quarantined rows and corrections recorded append-only.

### Manifests/reports/reproducibility
- Manifest required fields present, immutable, and linked to outputs.
- Re-run from identical manifest/inputs reproduces outputs or deterministic-equivalent hashes.
- Report displays/persists `resolved_as_of`, `generated_at/fetch_time`, run/manifest refs; fixed historical as-of independent of current date.
- Locked dependency install verified in CI/Docker.

### Evaluation
- Promotion gate fails when holdout/policy/cost/benchmark/manifest evidence missing.
- Gross/net and exposure-matched benchmark reported with declared assumptions.

## 4. Evidence capture template (per run/test)
- Date/time, environment, code SHA/dirty, branch/PR, command(s), dataset/snapshot/manifests, DB target (isolated/disposable), result (pass/fail), logs/artifacts paths, deviations, approver/reviewer.

## 5. Commands (to execute in approved implementation environment)
> Examples; adapt to repo tooling/CI. Run isolated DB tests only against disposable targets.

- `pytest -q` (or scoped suites: `tests/test_pit*`, `tests/test_dividend*`, `tests/test_adjust*`, `tests/test_manifest*`, `tests/test_reports*`)
- `python -m scripts.migrate` / migration command used by project (isolated DB)
- Reproducibility checks per `DEC-008` (e.g. locked install/build in CI and Docker)
- Lint/typecheck commands required by repo (discover via README/CI; record in `execution-log.md`)

## 6. Exit criteria for P0 validation claim
- All AC-P0 criteria have linked passing evidence or explicitly recorded, approved exceptions.
- RTM updated with evidence refs; no Partial/Missing promoted without verification.
- M1/contract decisions affecting behavior are recorded (`m1-decision-log-template.md`, decision tracker).
