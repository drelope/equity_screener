# P0 Acceptance Evidence Tracker

| Field | Value |
|---|---|
| Scope | `AC-P0-01..11` from `validation-plan.md` |
| Date | 2026-11-18 |
| Status | **0/11 fully verified** |
| Claim boundary | Local implementation scaffolding and validation are complete; no AC closure, promotion, or production cutover is authorized |

## Overall status

| Category | Count |
|---|---:|
| Fully verified | 0 |
| Partial local evidence | 9 |
| Not verified / blocked | 2 |
| External gates required | Named approver, DEC/UNK closure evidence, interactive UI confirmation, external CI run, controlled recompute/benchmark evidence |

## Acceptance criteria

| AC | Requirement | Current local evidence | Status | Missing acceptance evidence | Owner / next action |
|---|---|---|---|---|---|
| AC-P0-01 | Fixed `as_of` returns identical PIT-eligible universe across reruns | `us1-verification-2026-11-18.md`; `pit.py` as-of helpers; `pit-delta-2026-11-18.md` proxy | Partial | Approved membership backfill, fixed-as_of rerun evidence, current-state-change comparison | Quant/Data Lead after RM-01 readiness |
| AC-P0-02 | PIT recomputes reproduce historical universe/scores | V0107 candidate structure; synthetic backfill rehearsal; proxy delta only | Not verified / blocked | Controlled recompute log and diff report from approved PIT inputs | Quant/Data Lead; resolve UNK-003 |
| AC-P0-03 | No feature/signal uses data with `available_at > as_of` | V0108 timing columns; readiness checks; PIT draft metadata | Partial | Consumer cutover to availability gates, leak regression tests, golden late/amended filing cases | Data Engineering; resolve UNK-001/002 and DEC timing basis |
| AC-P0-04 | Adjusted series/total-return correct for split/dividend cases | Adjustment/dividend audits; `pit-delta` caveat posture | Not verified / blocked | Golden split/dividend cases, continuity checks, canonical basis decision | Data/Quant; resolve UNK-001/002 |
| AC-P0-05 | Deterministic batch dedupe; NULL date preservation; evidence retained | `scripts/populate_dividend_data.py` local tests; isolated duplicate-key/NULL-overwrite evidence | Partial | Approved precedence/key/feed-evidence contract and production-path validation | Data Engineering; close UNK-005 |
| AC-P0-06 | Ex-dividend/adjustment outputs carry basis/caveat labels | Report/caveat labels and manifest draft fields | Partial | UI/API/report assertions tied to approved basis policy | Product/Quant/App Lead |
| AC-P0-07 | Material runs produce immutable manifests with required fields | `run_manifest.py`, ledger candidates, opt-in persistence, 2,077 local tests | Partial | Approved immutable DB ledger/role model, production integration tests | Platform/Data; close V0110/V0111 promotion gates |
| AC-P0-08 | Scores/reports/AI outputs run-keyed and Reports Center provenance visible | `output_store.py`, dashboard as-of selector, static UI verification | Partial | Interactive browser UI confirmation, DB/API tests, historical report generation decision | App/UI Lead; complete UNK-004 |
| AC-P0-09 | Locked reproducible install/build in local/CI/Docker | DEC-008 exact pins + lock SHA-256 locally enforced, CI/Docker lock installs, local parity checker; external approval pending | Partial | External CI run URL and container build/install proof | Platform/DevOps |
| AC-P0-10 | Frozen holdout, versioned policy, cost/exposure-matched benchmark enforced | Draft promotion contract; named gaps; checker fails closed | Partial / blocked | Holdout freeze evidence, cost model values, exposure-matched benchmark, net metrics, approval | Quant Research; close DEC-002/003/004/005 |
| AC-P0-11 | Regression suite passes in CI | Local `pytest`: 2,077 passed, 0 failed; lint/format pass | Partial | External CI URL/log and test report artifact | Platform/DevOps |

## Required external evidence package

1. approver name [PENDING]; approval date 2026-11-19 owner-supplied, not effective until CI run URL and approved SHA are recorded.
2. DEC-001..008 and UNK-001..007 closure evidence or approved exceptions.
3. Interactive Reports Center verification (`unk004-ui-verification-checklist.md`).
4. CI run URL observed but not approved: `https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10` — owner-supplied CI job URL; page title identifies `Remove unsupported M1 approval claims and document CI evidence` at `64f74e1`; visible job `Security (dependency audit + secret scan)` failed with exit code 127 (`pip-audit` command not found); warning: Node.js 20 actions forced to Node.js 24; not a passing CI baseline; a passing run on the exact approved SHA is still required.
5. Controlled PIT recompute, survivor-vs-PIT delta, and approved basis decisions.
6. Frozen holdout, acceptance-policy version, cost model, exposure-matched benchmark, and net-return evidence.
7. Final AC review with named approver and decision date.

## External-evidence availability check (2026-11-18)

| Gate | Check | Result | Consequence |
|---|---|---|---|
| Named M1 approver | Supersedes `86f6a59` | approver name [PENDING]; approval date 2026-11-19 owner-supplied | Not effective approval; do not mark M1 complete |
| External CI |Supersedes `86f6a59` | `repository: https://github.com/drelope/equity_screener`; observed URL: `https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10`; approved SHA [PENDING] | owner-supplied CI job URL; page title identifies `Remove unsupported M1 approval claims and document CI evidence` at `64f74e1`; visible job `Security (dependency audit + secret scan)` failed with exit code 127 (`pip-audit` command not found); warning: Node.js 20 actions forced to Node.js 24; not a passing CI baseline; AC-P0-09/AC-P0-11 remain partial |
| Branch publication | `git branch -vv` | `feature/speckit-recovery` is local-only; no upstream | Branch must be pushed to a remote with CI before an external run can exist |

## Owner-supplied inputs (not effective)

| Field | Value | Status |
|---|---|---|
| approver name | [PENDING] | Supersedes `86f6a59`; no history rewrite |
| approval date | 2026-11-19 | Owner-supplied; not effective until CI run URL and approved SHA |
| repository | https://github.com/drelope/equity_screener | Repository only |
| CI run URL | https://github.com/drelope/equity_screener/actions/runs/45700975373/job/139510657402?pr=10 | Observed, not approved; failed job |
| approved SHA | [PENDING] | Exact commit SHA to be approved; observed CI page identifies 64f74e1 but is not an approved baseline |

## Non-claims

- This tracker does not close any AC-P0 criterion or record effective M1 approval/CI status. Observed CI: owner-supplied CI job URL; page title identifies `Remove unsupported M1 approval claims and document CI evidence` at `64f74e1`; visible job `Security (dependency audit + secret scan)` failed with exit code 127 (`pip-audit` command not found); warning: Node.js 20 actions forced to Node.js 24; not a passing CI baseline. M1 approval, CI status, merge, release, push, and tag remain BLOCKED.
- It does not authorize migration promotion, production cutover, or performance claims.
- It does not convert local scaffolding into external acceptance evidence.
