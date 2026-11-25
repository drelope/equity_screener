# Stage 1C Coverage Matrix

Behaviour area → existing tests → what they actually pin → gap → finding ID.

| Area | Existing tests | What they pin | Gap | TG |
|---|---|---|---|---|
| Dividend ingestion and normalization | `test_populate_dividend_data.py`, `test_openbb_client.py`, `test_dividend_limits.py` (via populate tests) | Provider parsing, basis adjustment, upsert shape, special/ROC flags | No executed SQL for the return build; SEC `filed` provenance not tested | TG-09, TG-17 |
| Corporate actions and split ratios | `test_load_corporate_actions.py`, `test_load_split_calendar.py`, `test_portfolio.py:518-553` | `denominator/numerator`, hash parity between loaders, happy-path split adjustment | Boundary tolerance/window/index-0; cross-convention equivalence | TG-08, TG-11 |
| Forward returns | `test_returns.py` (18 tests), `test_build_forward_returns.py` | SQL text fragments, `_db_value`, window planner | SQL never executed; no golden return decomposition | TG-09, TG-16 |
| Universe construction | `test_historical_universe.py` (3), `test_dividend_universe.py`, `test_feature_carry_forward.py`, `test_portfolio.py:402-422` | EDGAR index parsing, recency vs today, current `active=TRUE`, `security_type` filter | No as-of membership; no delisting; no test that selection uses only formation-date data | TG-04, TG-06 |
| Feature availability | `test_features.py` (1,168 lines), `test_label_targets.py`, `test_macro_vintages.py` | Price quality, fundamentals vintages, label windows, embargo | No `filed <= as_of` label eligibility test; no PIT universe | TG-17 |
| Walk-forward validation | `test_validation.py`, `test_walk_forward_checkpoint.py`, `test_label_targets.py`, `test_dry_run_walk_forward.py` | Purge/embargo arithmetic, gate/fold policy, checkpoint contract, synthetic sample | Broken dry-run `main()`, wrong default horizon, control tests absent | TG-01, TG-02, TG-03 |
| Backtest arithmetic | `test_backtest.py` (5), `test_portfolio.py` | Hand-computed chained returns, turnover, cash periods, schedule | No dividends, splits, volume; loader ignores date window | TG-06, TG-10 |
| Score production and history | `test_scoring.py`, `test_score_pruning.py`, `test_feature_carry_forward.py` | Weight/coverage rules, same-date stale-row pruning, carry-forward window | No replay immutability; no as-produced archive; `--as-of` overwrite untested | TG-07 |
| Calendar tables | `test_load_dividend_calendar.py` (6), `test_load_split_calendar.py` (4) | Window coverage, row construction, dedupe, upsert columns | No PIT query test; `CURRENT_DATE` view not exercised; no reader-absence guard | TG-05 |
| Macro and risk-free | `test_macro_vintages.py`, `test_macro_inputs.py`, `test_portfolio.py:192-216` | ALFRED as-of reader, latest observations, daily rate conversion | Production risk-free path not asserted to use as-of vintages | TG-18 |
| Identity and determinism | `test_identity.py`, `test_security_identity.py`, `test_merge_duplicate_identities.py`, `test_rekey_security_successor.py` | Resolution, merge/rekey behaviour | No frozen-clock determinism test; `date.today()` default unprotected | TG-19 |
| AI / worksheet | `test_analysis_autofill.py`, `test_llm_config.py`, `test_financial_analysis_skill.py` | Payload building, fallbacks, disabled-by-default LLM | As-of enforcement on autofill not tested (out of 1C scope; Stage 2 FR-AI) | — |
| CLI / ETL entry points | 11 modules calling `main()`, `test_run_full_etl_stages.py`, `test_stage_exit_codes.py`, `test_ops_catalog.py` | Selected exit codes, stage order, catalog metadata | 96 modules never call `main()`; dry-run/evaluate/backtest not invoked end-to-end | TG-15 |
| Suite instrumentation | — | — | No coverage tool, no threshold, no coverage artifact | TG-14 |

## Reading the Matrix

- "Existing tests" lists files that touch the area, not files that prove the audited property.
- The matrix separates **unit coverage** (often strong) from **contract coverage** (weak): the suite proves functions work on injected frames, but rarely proves the production loader passes the right window, the right universe, or the right revision.
- TG-16 is the cross-cutting finding: many rows above rely on SQL substring assertions. Executing every SQL constant against the migrated warehouse would convert several weak rows into real coverage.
