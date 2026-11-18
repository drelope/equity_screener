# Stage 1C Test Inventory

| Field | Value |
|---|---|
| Source | Stage 0 discovery (test pass), Stage 1A coverage notes, direct collection and execution in Stage 1C |
| Repo HEAD | `d748cea` |
| Date | 2026-11-15 |

## 1. Suite Shape

| Metric | Value | How verified |
|---|---|---|
| Test modules | 107 | `ls tests/test_*.py | wc -l` |
| Test functions | 1,686 | `grep "def test" tests/*.py | wc -l` |
| Collected tests | 1,929 | `pytest -q --collect-only` |
| Non-integration tests | 1,602 | `pytest -q --collect-only -m "not integration"` (327 deselected) |
| Integration-marked tests | 327 | `pytest -q --collect-only -m "integration"` |
| Modules declaring a DB probe | 18 | grep for `_live_engine` / `_database_ready` |
| `xfail` markers | 0 | grep `xfail` in `tests/` |
| `skip` / `skipif` sites | 82 | grep `pytest.skip` / `skipif` |
| Test modules that invoke a CLI `main()` | 11 of 107 | grep `\.main(` in `tests/` |
| Coverage configuration | None | no `.coveragerc`, no `[tool.coverage]`, no `pytest-cov` in `requirements-dev.txt` |

Pytest 8.4.2 is pinned in `requirements-dev.txt`; the installed interpreter reports 9.1.1 (Stage 0 DEP-F04).

## 2. How the Suite Is Gated

| Layer | Behaviour | Evidence |
|---|---|---|
| Local quality gate | `python -m scripts.crispdm_validate` runs `python -m pytest -q` | `scripts/crispdm_validate.py:26` |
| CI test job | Provisions Postgres 17.11, runs `init_db` + `migrate`, then bare `pytest -q` | `.github/workflows/ci.yml:31-55` |
| CI lint job | `ruff check` and `ruff format --check` | `.github/workflows/ci.yml:9-20` |
| CI security job | dependency audit + gitleaks | `.github/workflows/ci.yml:57+` |
| DB-less lane | `pytest -m "not integration"` (1,602 tests) | `tests/conftest.py:1-20` |
| DB present | Integration modules run; conftest `db_engine` / `db_conn` provide a rolled-back connection | `tests/conftest.py:40-60` |
| DB absent | `pytest.skip("no live database")` | `tests/conftest.py:50` |

There is no coverage report, no threshold, and no per-module minimum.

## 3. Test Styles in Use

| Style | Description | Representative files | Strength | Limitation |
|---|---|---|---|---|
| Pure unit, injected loaders | Business arithmetic on hand-built frames | `test_backtest.py`, `test_portfolio.py`, `test_returns.py` | Fast, deterministic | Loader contracts can drift; window arguments are not asserted |
| Source-text guard | Reads source/SQL constants and asserts substrings | `test_returns.py`, `test_score_pruning.py`, `test_feature_carry_forward.py` | Cheap regression guard for policy text | Cannot prove SQL parses or runs (TG-16) |
| Fake-query capture | Injects a `query` callable and inspects SQL/params | `test_portfolio.py:402-422`, `test_dividend_universe.py` | Checks predicates and parameters without DB | Pins current SQL text, not as-of behaviour |
| Live-DB integration | Runs against migrated Postgres, often inside a rolled-back transaction | `test_score_pruning.py`, `test_feature_carry_forward.py`, `test_analysis_store.py` | Executes real SQL | Depends on warehouse state; no snapshot pin |
| CLI `main()` | Calls entry point with patched I/O | 11 modules, e.g. `test_build_forward_returns.py`, `test_stage_exit_codes.py` | Catches signature drift | Most entry points are never called (TG-15) |
| Synthetic end-to-end | Builds a labelled frame and runs `walk_forward` | `test_dry_run_walk_forward.py` | Exercises the gate logic | Does not run the advertised script (TG-01) |

## 4. Coverage by Audit Area

See `coverage-matrix.md` for the per-area table. Summary:

| Area | Existing coverage | Test gap |
|---|---|---|
| Split / dividend lineage | Strong unit coverage of loaders, conventions, and split adjustment | Boundary values (PA-P07), cross-convention (PA-P17), executed return SQL (PA-P15) |
| Universe | Parser, recency, current `active` predicates | No as-of membership or delisting test (TG-04) |
| Calendar | Loader row/window/upsert behaviour | No PIT test; guard is absence of readers (TG-05) |
| Features / labels | Large unit suite; label windows | SEC `filed` gate (TG-17), PIT universe |
| Walk-forward | Gate, folds, checkpoint, embargo | Broken entry point (TG-01), wrong default (TG-02), controls (TG-03) |
| Backtest | Hand-computed returns, cash, turnover | No dividend/split/volume; window ignored (TG-06, TG-10) |
| Scores | Score policy and same-date pruning | Replay immutability / as-produced archive (TG-07) |
| Macro | Vintage reader and inputs | Production risk-free path not wired to as-of (TG-18) |

## 5. Verification Runs Performed in Stage 1C

| Command | Result |
|---|---|
| `python -m pytest -q --collect-only` | 1,929 tests collected in 40.78s |
| `python -m pytest -q --collect-only -m "not integration"` | 1,602 collected, 327 deselected |
| `python -m pytest -q --collect-only -m "integration"` | 327 collected, 1,602 deselected |
| `python -m pytest -q` on 16 gap-area modules | **302 passed**, 0 failed, 0 skipped in 166.39s (DB reachable) |
| `python -m scripts.dry_run_walk_forward --out /tmp/wf_dry.json` | **Failed**: `TypeError: walk_forward() got an unexpected keyword argument 'min_recall'`, exit 1 |
| `python -m pytest -q tests/test_dry_run_walk_forward.py tests/test_validation.py` | **11 passed** despite the broken script |
| DB probe | `SELECT current_database()` returns `dividend`; warehouse reachable |
| `inspect.signature` | `walk_forward(df, max_flag_rate, features, embargo_days)`; `make_checkpoint` has 9 parameters |

The 16-file targeted set: `test_dry_run_walk_forward`, `test_validation`, `test_backtest`, `test_portfolio`, `test_features`, `test_returns`, `test_historical_universe`, `test_dividend_universe`, `test_load_dividend_calendar`, `test_load_split_calendar`, `test_score_pruning`, `test_feature_carry_forward`, `test_label_targets`, `test_walk_forward_checkpoint`, `test_build_forward_returns`, `test_macro_vintages`.

## 6. Notes and Limits

- Stage 1A reported 398 passed over 22 targeted files. That list was not preserved, so Stage 1C did not reproduce the same number; it ran a new 16-file set aimed at the Stage 1B handoff.
- The suite's green state is not evidence that the audited defects are absent. TG-01 and TG-04 show tests that pass while the corresponding behaviour is broken or survivor-only.
- No test was added or modified in this stage.
