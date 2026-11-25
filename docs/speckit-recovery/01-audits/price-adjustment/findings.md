# Stage 1A Findings Register (Price Adjustment, Dividends, Corporate Actions)

| Field | Value |
|---|---|
| Stage | 1A — Price adjustment audit |
| ID prefixes | PA-D (dividend ingestion, from dividend-adjustment-audit.md), PA-P (price and return paths), PA-F (features, event study) |
| Companion files | `dividend-adjustment-audit.md`, `formula-inventory.md` (FA-), `adjustment-lineage.md` |
| Requirement IDs | TBD — assigned in Stage 2 |

Row format: ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type

## 1. Summary

| Area | Count | Highest risk |
|---|---|---|
| Dividend ingestion (PA-D) | 22 | High |
| Price and return paths (PA-P) | 21 | High |
| Feature and event study (PA-F) | 6 | High |

Stage 0 live checks already confirmed `raw.market_data.adjusted_close` is 100% NULL (0 of 9,823,774 rows). Whether stored `close` is split-adjusted is **Unknown** (not queried); several findings below depend on that.

## 2. Price and Return Paths (PA-P)

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| PA-P01 | Real price moves up to ±10% on a split day are absorbed into the split factor, so pre-split levels are off by the same amount and the split-day return is forced to 0 | Experiment: 2-for-1 split with −10% real move gave closes `[45.0, 45.45, 45.45, 46.0, 46.5]`, split-day return 0 | `src/crispdm/portfolio.py` | `clean_prices` (L714-719) | FR-ADJ | Data Preparation | High | Compare observed ratio to reported ratio on the event date; flag disagreement instead of absorbing | 0.9 | Verified |
| PA-P02 | A real move above 10% on a split day is not adjusted; the split appears as a one-day crash that enters downstream return calculations | Experiment: −15% real move, `splits_adjusted = 0` | `src/crispdm/portfolio.py` | `clean_prices` | FR-ADJ | Data Preparation | High | Apply reported ratio when a split event is confirmed by calendar, and record the residual | 0.8 | Verified (count); downstream Inferred |
| PA-P03 | Risk-parity path weights by `risk_score` (1 − percentile of volatility), not volatility, with inverted direction | `_risk_parity_weights(longs, "risk_score", ...)`; `risk_score = pct(volatility_252d, False)` | `src/crispdm/portfolio.py`; `src/crispdm/scoring.py` | `_risk_parity_weights`; `score` (L93-95, L211) | FR-PORT | Modeling | High | Use `volatility_252d` with `w ∝ 1/σ`, or remove the flag. Default book unaffected | 0.9 | Verified |
| PA-P04 | Validated baseline uses inverse-vol weights from full-period volatility (look-ahead), omits `split_events` in cleaning, and fixes the universe at the first date | `aligned.std() * sqrt(252)` over full window; `clean_prices(prices_for(...))` with no split events | `src/crispdm/backtest.py` | `run_walk_forward_validated` (L294-315) | FR-BT / NFR-PIT | Evaluation | Critical | Pass `split_events`; compute σ from data up to each formation date; document fixed universe | 0.95 | Verified |
| PA-P05 | Backtest security selection uses price-quality information up to 14 calendar days after the formation date | `prices_for(ids, start, end + CLEANING_LOOKAHEAD)`; `exclude_unreliable` | `src/crispdm/backtest.py`; `src/crispdm/portfolio.py` | `run_walk_forward` (L88-95); `exclude_unreliable` (L772-777) | FR-BT / NFR-PIT | Evaluation | High | Restrict cleaning and rejection share to data available at formation date, or document as known look-ahead | 0.85 | Verified |
| PA-P06 | Dividend equal to prior close is credited (inclusive boundary); behaviour at exactly the cap is untested | `dividend.where(dividend <= 1.0 * previous, 0.0)`; closes 100,100 + div 100 → return 1.0 | `src/crispdm/portfolio.py` | `total_return_matrix` (L332) | FR-TR | Data Preparation | Low | Add boundary test; decide strict vs inclusive | 0.9 | Verified |
| PA-P07 | Split tolerance (10%), event window (5 days), and first-print skip have no tests | No test references `SPLIT_TOLERANCE`, `SPLIT_EVENT_WINDOW_DAYS`, `_event_index` | `src/crispdm/portfolio.py`; `tests/test_portfolio.py` | `clean_prices`, `_event_index` | NFR-TEST | Evaluation | High | Add boundary tests for tolerance, window, and index-0 | 0.9 | Verified (absence) |
| PA-P08 | Cash periods are indexed on weekdays (`bdate_range`), including holidays, so annualization N counts non-trading days | `_cash_period` (L206); `performance_metrics` uses N | `src/crispdm/backtest.py`; `src/crispdm/portfolio.py` | `_cash_period`; `performance_metrics` (L373) | FR-BT | Evaluation | Med | Use the exchange calendar for cash index | 0.85 | Verified (code); impact Inferred |
| PA-P09 | Pre-listing and missing days are filled with 0 return in VaR and position returns | `frame.fillna(0.0) @ weights` (L446-448); `(1 + returns.fillna(0)).prod()` (L504-508) | `src/crispdm/portfolio.py` | `risk_metrics`, `position_returns` | FR-RISK | Evaluation | Med | Use holding-period returns; exclude pre-listing days | 0.9 | Verified (code); bias Inferred |
| PA-P10 | Parametric covariance uses `dropna(how='any')`, so one missing name shortens the sample | `complete = frame.dropna(how='any')` (L455) | `src/crispdm/portfolio.py` | `risk_metrics` | FR-RISK | Evaluation | Med | Use pairwise covariance with minimum overlap, or report the effective sample | 0.9 | Verified |
| PA-P11 | Sector attribution fills missing returns with 0, and computes excess return for shorts with the same sign convention | `fillna(0)` (L539); `excess = r − portfolio_return` | `src/crispdm/portfolio.py` | `sector_attribution` (L534-557) | FR-ATTR | Evaluation | Low | Document convention; test short-side sign | 0.85 | Verified |
| PA-P12 | A dividend on a row with a missing close is dropped silently by the matrix path | Closes `[100, NaN, 110]` + div 5 on NaN row → `[NaN, 0.1]` | `src/crispdm/portfolio.py` | `total_return_matrix` (L318-321) | FR-TR | Data Preparation | Low | Credit to next priced row, as `FORWARD_RETURN_SQL` does; note SQL path already guards | 0.85 | Verified (behaviour); SQL impact Inferred low |
| PA-P13 | A split dated the same day as an ex-date is not applied to that dividend (strict `>`) | `_later_factor` strict inequality | `src/crispdm/openbb_client.py` | `_later_factor` (L230-235) | FR-ADJ | Data Preparation | Med | Confirm intended basis; test the case | 0.6 | Verified (behaviour); correctness Inferred |
| PA-P14 | Same-day multiple payments are summed before the single-payment sanity guard | `SUM(e.amount)` then `CASE WHEN dv.amount <= ratio * LAG(close)` | `src/crispdm/returns.py`; `src/crispdm/portfolio.py` | `FORWARD_RETURN_SQL` (L108-123); `PRICE_SQL` (L119-131) | FR-TR | Data Preparation | Med | Apply guard per payment before summing; test | 0.8 | Verified (code); impact Inferred |
| PA-P15 | Forward-return and price SQL are never executed by any test; coverage is substring checks only | `in` assertions in `tests/test_returns.py` L22-56 | `tests/test_returns.py`; `tests/test_features.py` | — | NFR-TEST | Evaluation | High | Add DB-backed golden test with known dividend, split, ex-date | 0.95 | Verified |
| PA-P16 | Backtest tests have no dividend column and pass no split events | `_prices` has no dividend; `_run` passes no `split_events` | `tests/test_backtest.py` | `_prices`, `_run` | NFR-TEST | Evaluation | High | Add dividend and split fixtures to backtest | 0.9 | Verified |
| PA-P17 | Two split-ratio conventions (Yahoo divisor vs corporate-actions multiplier) are pinned separately with no cross-check | `openbb_client` vs `load_corporate_actions`/`load_split_events` | `src/crispdm/openbb_client.py`; `scripts/load_corporate_actions.py`; `src/crispdm/portfolio.py` | `_later_factor`; `split_rows`; `load_split_events` | NFR-TEST | Evaluation | Med | Add a test that both conventions agree on the same event | 0.8 | Verified |
| PA-P18 | Rounding and numeric precision are effectively untested | Only `pytest.approx` and `_db_value` NaN handling | `tests/` | — | NFR-TEST | Evaluation | Med | Add precision tests for LN/EXP compounding and NUMERIC storage | 0.85 | Verified (absence) |
| PA-P19 | Same-date duplicate split events are applied once only because the second fails the tolerance test | Two identical events → `splits_adjusted = 1` | `src/crispdm/portfolio.py` | `clean_prices` | NFR-DET | Data Preparation | Low | Deduplicate events explicitly; add test | 0.8 | Verified |
| PA-P20 | Test name `test_price_quality_keeps_a_sub_floor_price_that_is_its_own_median` contradicts its assertion (expects SUB_PENNY flag) | Test asserts `PRICE_QUALITY_SUB_PENNY` | `tests/test_features.py` | test at L229 | NFR-TEST | Evaluation | Low | Rename test or fix expectation | 0.9 | Verified |
| PA-P21 | Total return and dividend credit use different price bases for the same security: `returns.py` log returns; `portfolio.py` simple returns and forward-filled closes | `LN(...)` vs `(close + div)/prev − 1` with `ffill` | `src/crispdm/returns.py`; `src/crispdm/portfolio.py` | `FORWARD_RETURN_SQL`; `total_return_matrix` | FR-TR | Evaluation | Low | Document equivalence; add cross-check test on a shared fixture | 0.9 | Verified (math equal over full window) |

## 3. Dividend Ingestion (PA-D)

Full detail in `dividend-adjustment-audit.md` §3. Summary of IDs:

| ID | Short description | Risk |
|---|---|---|
| PA-D01 | SEC `ex_dividend_date` = period end; filing date dropped | High |
| PA-D02 | Fundamentals dividend fallback reads before filing (look-ahead) | High |
| PA-D03 | SEC merge key collapses all filings for one period end | High |
| PA-D04 | OPENBB ex-date falls back to payment date | High |
| PA-D05 | Leap-day `ValueError` in plausibility horizon | Med |
| PA-D06 | Date fields overwritten with NULL on re-run | High |
| PA-D07 | No per-row error handling in insert loop | Med |
| PA-D08 | Duplicate-PK-in-batch behaviour unverified | Med (Unknown) |
| PA-D09 | Frequency is security-level, stamped per row | Low |
| PA-D10 | CashPaid treated inconsistently across ingest and views | Med |
| PA-D11 | Special flag only from provider label | Low |
| PA-D12 | Absurd OpenBB rows dropped silently, not quarantined | Med |
| PA-D13 | Quarantine rule written only by one-time migration | Med |
| PA-D14 | Yahoo-only amounts not restated; basis is assumed | High |
| PA-D15 | Later provider exception swallowed after empty result | High |
| PA-D16 | "No evidence" from Polygon stored as "unresolved" | Med |
| PA-D17 | Verdict cache and 7-day recheck undocumented/untested | Med |
| PA-D18 | Payer universe rule (keep existing, never create) | Low |
| PA-D19 | Payer universe defaults to `date.today()` | Med |
| PA-D20 | Calendar events never deleted | Med |
| PA-D21 | Calendar and upcoming view have no code consumer | Low |
| PA-D22 | Frequency bucket thresholds | Low |

## 4. Feature and Event Study (PA-F)

| ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type |
|---|---|---|---|---|---|---|---|---|---|---|
| PA-F01 | XBRL-based dividend fallback in features can use a figure before filing (same root as PA-D02) | `d_declared` joins `ex <= observation_date`; ex = period end | `src/crispdm/features.py` | `build_features` (L774-781) | FR-FEAT / NFR-PIT | Data Preparation | High | Add filing-date lag | 0.85 | Verified (SQL); impact Inferred |
| PA-F02 | Dividend growth windows share the boundary day `obs − 365`, double-counting an event on that day | Both windows include `obs − 365` (L815-816 vs L827-828) | `src/crispdm/features.py` | `dividend_growth` | FR-FEAT | Data Preparation | Low | Use half-open windows | 0.8 | Verified (SQL); impact Inferred small |
| PA-F03 | Payout ratios divide an OPENBB annual dividend (split-restated) by SEC EPS; basis compatibility not established | `earnings_payout = annual / eps_ttm` | `src/crispdm/features.py` | payout features (L1282-1286) | FR-FEAT | Data Preparation | Med | Verify per-share basis on a sample; document | 0.5 | Unknown |
| PA-F04 | Price-quality median uses full stored price history (look-ahead for historical as-of) | `percentile_cont(0.5)` over whole history | `src/crispdm/features.py` | `classify_price_quality` (L559-602, L888-894) | FR-FEAT / NFR-PIT | Data Preparation | High | Replace with trailing median up to as-of date | 0.95 | Verified |
| PA-F05 | Yield band (`1e-6`–`0.25`) is a symptom guard for unadjusted reverse splits; root cause not fixed at source | WHLR test pins yield NaN for `5.75e-12` | `src/crispdm/features.py`; `tests/test_features.py` L133 | `null_implausible_yields` (L281-320) | FR-ADJ | Data Preparation | High | Fix split adjustment of closes (PA-P01/P02) so the guard is a backstop only | 0.9 | Verified (test); root cause Inferred |
| PA-F06 | Event study blanks daily returns above 50% but does not detect splits; a 2-for-1 gives r ≈ −0.5 and passes; split-adjustment of PRICES_SQL closes is not verified | `daily_returns` (L74-75); `PRICES_SQL` raw close (`scripts/event_study.py` L26-31) | `src/crispdm/event_study.py` | `daily_returns` | FR-ADJ | Evaluation | High | Use split-adjusted closes or a split-event mask; add test with 2-for-1 | 0.6 | Inferred |

## 5. Cross-Reference to Stage 0 Findings

| Stage 0 ID | Relation to Stage 1A |
|---|---|
| DF-F01 (adjusted_close 100% NULL) | Confirms no stored adjusted series; basis of closes is FA-U01 |
| DF-F02 (provider collapsed to OPENBB) | Prevents auditing split basis per row (lineage gap 4) |
| DF-F04 (FMP restated to Yahoo basis) | Confirmed by code (PA-D14, PA-P13) |
| DF-F05 (dividend conflict key excludes feed) | Upsert analysis, PA-D06 |
| DF-F09 (XBRL rows excluded from TR) | Confirmed in `returns.py` L105-108 |
| CMP-F09 (adjusted_close NULL) | Same as DF-F01 |

## 6. Recommended Priority

| Priority | IDs | Reason |
|---|---|---|
| P0 | PA-P04, PA-P05, PA-D01, PA-D02, PA-F01, PA-F04 | Look-ahead in selection, validation, and features |
| P0 | PA-D06 | Silent overwrite of dates on re-run |
| P1 | PA-P01, PA-P02, PA-F05, PA-F06, PA-D14 | Split handling gaps in price series |
| P1 | PA-P03 | Risk-parity direction (flag only, default off) |
| P1 | PA-P07, PA-P15, PA-P16 | Test gaps on the adjustment paths |
| P2 | PA-P08–PA-P14, PA-P17–PA-P21, PA-D05, PA-D07, PA-D10, PA-D12, PA-D13, PA-D15–PA-D22 | Hardening and documentation |

## 7. Verification Status

| Claim | Status |
|---|---|
| Targeted pytest run, 22 files | 398 passed, 0 failed, exit 0 (agent-reported; output not independently re-run in this step) |
| Live DB checks used | Stage 0 queries only; no new live query in Stage 1A |
| Experiments PA-P01, PA-P02, PA-P19, PA-P12 | Run by audit agent on synthetic inputs calling production functions; not committed as tests |
