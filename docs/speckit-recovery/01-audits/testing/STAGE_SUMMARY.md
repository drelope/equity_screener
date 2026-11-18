# Stage 1C — Testing Review: Stage Summary

| Field | Value |
|---|---|
| Status | Complete (review); no source, test, or config changes |
| Output | `docs/speckit-recovery/01-audits/testing/` |
| Inputs | `00-discovery/` test inventory; `01-audits/price-adjustment/`; `01-audits/bias/` |
| Repo HEAD | `d748cea` |
| Date | 2026-11-15 |

## 1. What Was Done

| Pass | Scope | Outcome |
|---|---|---|
| Inventory | Counted modules/tests, markers, DB gating, CLI entry points, coverage tooling | 107 modules, 1,929 collected (1,602 non-integration / 327 integration), 0 xfail, no coverage config |
| Stage 1A follow-up | Re-checked PA-P07, PA-P15, PA-P16, PA-P17, PA-P18, PA-P20 against current tests | All six gaps persist; TG-08…TG-13 |
| Stage 1B follow-up | Re-checked BI-28, BI-29, BI-33, LP-10/LP-12/LP-14/LP-23 | BI-29 reproduced by execution; BI-28 and BI-33 still untested; LP-10/LP-12/LP-14 untested; LP-23 guarded only by absence |
| Execution | Ran a 16-module gap-area set against the live warehouse; ran the dry-run script | 302 passed, 0 failed/skipped; dry run raises `TypeError` |
| Cross-cutting | Classified test styles (unit, source-text, fake-query, live DB, CLI) and identified false confidence | SQL substring assertions and unexecuted entry points are systemic |

## 2. Files Produced

| File | Contents |
|---|---|
| `findings.md` | TG-01…TG-20 register in the mandated row format; input cross-reference; severity rationale; limits |
| `coverage-matrix.md` | Area → existing tests → what they pin → gap → TG ID |
| `test-inventory.md` | Suite shape, gating, test styles, verification commands and results |
| `STAGE_SUMMARY.md` | This file |

## 3. Headline Results

| Rank | Result | Type | Confidence |
|---|---|---|---|
| 1 | The documented dry-run walk-forward command is broken (`walk_forward(min_recall=...)`; six-argument `make_checkpoint` vs nine) and no test executes it. The suite is green (11/11 in the two related modules) while `python -m scripts.dry_run_walk_forward` exits 1 with `TypeError`. | False confidence | 1.0 |
| 2 | No coverage tooling or threshold exists. CI and the local quality gate run bare `pytest -q`; `pytest-cov` is not installed. Line/branch coverage is unknown. | Tooling gap | 1.0 |
| 3 | Universe membership is never tested as of a historical date. Tests pin current-state `s.active=TRUE` in feature/scoring SQL and assert only `security_type` in the universe query, so a survivor-only universe is green. | Missing test | 0.95 |
| 4 | Backtest tests cannot detect LP-12: the injected `prices_for(ids, start, end)` ignores the requested window, and fixtures carry no volume/dividends/splits. Post-formation eligibility is unobservable to the suite. | Missing test | 0.95 |
| 5 | Score replay immutability is untested. `model.scores`/`rankings` are keyed by `(security_id, as_of_date)` and upsert-overwrite; `test_score_pruning` protects same-date stale rows, not historical re-scores. | Missing test | 0.9 |
| 6 | Many SQL paths are asserted as substrings, never executed. `FORWARD_RETURN_SQL` and `UNIVERSE_SQL` have no DB-executed test; a malformed query can pass. | Weak test | 0.9 |
| 7 | Validation helpers default to 63 days while the label horizon is 365, and the tests pass 63 explicitly — the suite pins the wrong default (BI-28). | Pinned defect | 0.95 |
| 8 | BI-33's controls (sort before walk-forward, disjoint backtest periods, cash-period start exclusion) have no regression tests; they were verified by code read only. | Missing test | 0.9 |
| 9 | Calendar tables have loader tests only. `raw.upcoming_dividends` uses `CURRENT_DATE`; the PIT guard is the absence of readers, and nothing tests that absence. | Missing test | 0.9 |
| 10 | Target run: 302 passed, 0 failed, 0 skipped over 16 gap-area modules; DB reachable. Only 11 of 107 test modules call a script `main()`. | Verified (run) | 1.0 |

## 4. Verification Log

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest -q --collect-only` | 1,929 collected (40.78s) |
| `--collect-only -m "not integration"` | 1,602 collected, 327 deselected |
| `--collect-only -m "integration"` | 327 collected, 1,602 deselected |
| 16-module targeted run | **302 passed**, 0 failed, 0 skipped (166.39s) |
| `.venv/bin/python -m scripts.dry_run_walk_forward --out /tmp/wf_dry.json` | `TypeError: walk_forward() got an unexpected keyword argument 'min_recall'`; exit 1 |
| `pytest -q tests/test_dry_run_walk_forward.py tests/test_validation.py` | 11 passed (green while the script is broken) |
| `inspect.signature` | `walk_forward(df, max_flag_rate, features, embargo_days)`; `make_checkpoint` 9 parameters |
| DB probe | `current_database()` = `dividend`; reachable |

The 16 modules: `test_dry_run_walk_forward`, `test_validation`, `test_backtest`, `test_portfolio`, `test_features`, `test_returns`, `test_historical_universe`, `test_dividend_universe`, `test_load_dividend_calendar`, `test_load_split_calendar`, `test_score_pruning`, `test_feature_carry_forward`, `test_label_targets`, `test_walk_forward_checkpoint`, `test_build_forward_returns`, `test_macro_vintages`.

## 5. Unknowns and Limits

| ID | Unknown | Why it matters |
|---|---|---|
| U-1 | Actual line and branch coverage | Without it, TG-14 cannot be prioritised against specific modules; installing coverage is a config change deferred to remediation |
| U-2 | The exact Stage 1A 22-file/398-test list | Stage 1C's 302-test run is a new gap-area sample, not a reproduction of the 1A number |
| U-3 | Warehouse snapshot used by live tests | Live tests prove execution, not hermeticity; a different warehouse state may change results |
| U-4 | When the dry run last passed and what changed (`walk_forward`/`make_checkpoint` signatures) | Docs still claim `-> PASS`; the break predates this stage and was not bisected |
| U-5 | Whether any external pipeline runs `dry_run_walk_forward` or `evaluate_walk_forward` | CI runs only pytest, so the broken entry point is invisible there |

## 6. Handoff to Next Stages

| Stage | Inputs from 1C |
|---|---|
| 1D Determinism and auditability | TG-19 (`date.today()` determinism), TG-01/TG-15 (entry point execution), TG-07 (as-produced archive), TG-03 (ordering controls) |
| Stage 2 Requirements | NFR-TEST: coverage gate, DB-executed SQL contract, PIT regression suite, entry-point smoke tests, no-green-on-known-defect policy. FR-UNI/FR-EVAL/FR-BT/FR-DIV/FR-FEAT/FR-MACRO/FR-AI acceptance criteria should cite TG-04/06/07/09/17/18/05 |
| Stage 3 Constitution | Candidate MUSTs: every point-in-time guard has a regression test; every documented command is executed by CI; open audit findings are fixed or strictly `xfail`-pinned, never silently green |
| Remediation (post-stage) | Fix TG-01 and TG-02 first, then add TG-04/06/07 regression tests before any survivorship or replay correction lands |

## 7. Next Step

Stage 1D (determinism and auditability) is next in the SpecKit sequence, using the 1B inputs BI-04, BI-12, BI-24, BI-32, BI-38 and this stage's TG-19/TG-07.

Stage 2 as requested in the handoff (FR-UNI, FR-EVAL, FR-BT, FR-DIV, FR-FEAT, FR-MACRO, FR-AI, NFR-PIT, NFR-GOV, NFR-REPRO) has **no requirements document yet** — those IDs are TBD by design. A Stage 2 *validation* cannot run until the requirements register exists; Stage 1C supplies the testability evidence it needs.

No tests were created or modified in this stage. The findings specify the tests to add; implementing them is remediation work and should follow the fix for each broken behaviour (not precede it with failing tests unless marked `xfail`).
