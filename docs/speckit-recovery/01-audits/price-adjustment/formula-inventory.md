# Formula Inventory (Stage 1A)

| Field | Value |
|---|---|
| Stage | 1A — Price adjustment audit |
| ID prefix | FA- (formula) |
| Method | Read of named functions; formulas quoted from code |
| Type key | V = Verified (read), I = Inferred, A = Assumption, U = Unknown |

Row format: ID | Finding | Evidence | File path | Function/Class | Requirement ID | CRISP-DM phase | Risk | Recommended action | Confidence | Type

## 1. Formula Register

| ID | Formula | Code | File / function | Notes | Type |
|---|---|---|---|---|---|
| FA-S01 | Split-basis dividend restatement: `adj = amount / Π{ r_s : split_date_s > ex_date }` | `adjusted.append(amount / _later_factor(splits, ex_date))` | `src/crispdm/openbb_client.py` `_price_basis_adjust`, `_later_factor` (L230-261) | Strict `>`: split on ex-date not applied (FA-S03). No rounding. Overwrites FMP `adjDividend`. | V |
| FA-S02 | Split ratio, corporate actions: `ratio = denominator / numerator` | `ratio = denominator / numerator` | `scripts/load_corporate_actions.py` `split_rows` (L71) | 2-for-1 → 0.5. Opposite convention to Yahoo factor used as divisor in FA-S01 (FA-S04). | V |
| FA-S03 | Strict inequality on split date vs ex-date | `if split_date > ex_date` | `src/crispdm/openbb_client.py` `_later_factor` (L230-235) | Same-day split not applied to same-day dividend. Correctness Inferred (0.6). | V |
| FA-S04 | Two ratio conventions coexist | Yahoo: factor 1.5 divides amount; corporate_actions: 0.667 multiplies close | `openbb_client.py` vs `load_corporate_actions.py` / `portfolio.load_split_events` | No test asserts the two agree on one event. | V |
| FA-P01 | Price-split adjustment: `close[:i] *= observed` where `observed = close[i]/close[i-1]` | applied if `abs(observed/expected − 1) <= SPLIT_TOLERANCE (0.10)` within `SPLIT_EVENT_WINDOW_DAYS (5)` | `src/crispdm/portfolio.py` `clean_prices` (L701-719), `_event_index` (L780-790) | Applied only in `clean_prices`. Absorbs real moves ≤10% into split factor (PA-P02). | V |
| FA-P02 | Daily total return (simple): `(P_t + D_t) / P_{t-1} − 1` | `matrix = (close + valid_dividend) / previous - 1.0` | `src/crispdm/portfolio.py` `total_return_matrix` (L301-334) | Close forward-filled before differencing (bridges gaps). | V |
| FA-P03 | Daily log total return (SQL): `LN((close + D_credit) / LAG(close))` | `LN((m.close + CASE WHEN dv.amount <= :max_payment_ratio * LAG(m.close) ... ) / NULLIF(LAG(m.close), 0))` | `src/crispdm/returns.py` `FORWARD_RETURN_SQL` (L127-130) | Credit on first priced row on/after ex-date (L116-122). Never executed by tests. | V |
| FA-P04 | Forward total return over 252 rows: `EXP(SUM(log_total)) − 1`; price return analogous; `dividend_return = total − price` | L138-153 | `src/crispdm/returns.py` | Complete-window check `window_days = 252`. | V |
| FA-P05 | Dividend guard: credit only if `dividend <= 1.0 × prior_close` | `MAX_SINGLE_PAYMENT_RATIO = 1.0` | `returns.py` L70, L128; `portfolio.py` L332; `features.py` L248 | Inclusive boundary (PA-P06). Summed same-day payments tested as one amount (PA-P05). | V |
| FA-P06 | Portfolio NAV: `nav_t = (1 + Σ_i w_i r_{i,t}) cumulative × BASE_NAV` (constant weights, daily rebalanced) | `contribution.sum(axis=1)`; `(1 + daily).cumprod() * BASE_NAV` | `src/crispdm/portfolio.py` `portfolio_returns` (L337-348) | Weights not renormalised when names are missing. | V |
| FA-P07 | Backtest period return: `Π(1 + r_t) − 1` over `(start, end]` | `prod(1 + book_return) − 1` | `src/crispdm/backtest.py` (L112-136) | Returns strictly after formation close. | V |
| FA-P08 | Turnover (one way): `0.5 × Σ|w_t − w_{t−1}|` | L135, L210-215 | `src/crispdm/backtest.py` | Cash resets previous weights. | V |
| FA-P09 | Benchmark (backtest): equal-weight mean of simple daily returns over scored cleaned universe, daily rebalanced; cash periods benchmark = 0 | `window[universe_ids].mean(axis=1, skipna=True).fillna(0.0)` | `src/crispdm/backtest.py` (L128-133), `_cash_period` (L204-207) | Universe fixed at formation date. | V |
| FA-P10 | Annualized return: `nav_end^(252/N) − 1` | L373 | `src/crispdm/portfolio.py` `performance_metrics` | N = number of daily observations; cash days from `bdate_range` inflate N (PA-P08). | V |
| FA-P11 | Annualized volatility: `std(ddof=1) × √252` | L374 | `performance_metrics` | | V |
| FA-P12 | Sharpe: `mean(excess)/std(excess) × √252` | L365-370, L385-388 | `performance_metrics` | `excess = r − rf_daily` only if rf covers every date. | V |
| FA-P13 | Sortino: `mean(r) / √mean(min(r,0)²) × √252` | L377, L389 | `performance_metrics` | | V |
| FA-P14 | Max drawdown: `min(nav/cummax(nav) − 1)` | L372, L378 | `performance_metrics` | | V |
| FA-P15 | Information ratio: `mean(active)/std(active) × √252`, active = `r − benchmark` | L399-405 | `performance_metrics` | Inner-joined dates. | V |
| FA-R01 | Historical VaR: `−nanpercentile(portfolio, α×100)`; `portfolio = frame.fillna(0) @ w` | L446-448 | `src/crispdm/portfolio.py` `risk_metrics` | Pre-listing days treated as 0 return (PA-P09). | V |
| FA-R02 | Expected shortfall: `−mean(portfolio[portfolio ≤ q])` | L449-450 | `risk_metrics` | | V |
| FA-R03 | Parametric VaR: `z × √(wᵀΣw)`, `z = Φ⁻¹(confidence)` | L457-459, L478 | `risk_metrics` | Covariance on `frame.dropna(how='any')` (PA-P10). | V |
| FA-R04 | Component VaR: `comp_i = w_i (Σw)_i / σ_p × z`; contribution = comp / Σcomp | L460-468 | `risk_metrics` | Sums to 1 by construction. | V |
| FA-R05 | Position return: `Π(1 + r_i)` over full loaded window − 1 | L504-508 | `portfolio.position_returns` | Not holding-period specific. | V |
| FA-R06 | Sector alpha: `Σ(excess_i |w_i|)/Σ|w_i|` per sector; `excess_i = r_i − portfolio_return` | L534-557 | `portfolio.sector_attribution` | Missing returns filled with 0 (PA-P11). | V |
| FA-R07 | Risk-parity weights: `RiskParityCalculator.calculate_weights(risk_score)` with `risk_score = 1 − pct_rank(vol_252d)` | `portfolio.py` L242-248, L282-290; `scoring.py` L93-95, L211 | `risk_parity=True` path only | Inputs are a percentile, not volatility; direction inverted (PA-P03). Default book unaffected. | V |
| FA-R08 | Inverse volatility (math engine): `w_i = (1/σ_i) / Σ_j(1/σ_j)` | `inverse_volatility = 1.0 / values; return inverse_volatility / inverse_volatility.sum()` | `src/math_engine.py` `RiskParityCalculator` | Named "risk parity" but is inverse-vol, not equal risk contribution. | V |
| FA-B01 | Inverse-vol baseline: `w_i ∝ 1/σ_i`, `σ` clipped ≥ 1e-6, missing σ filled with mean | L27-34 | `src/crispdm/baselines.py` | Validated path uses full-period σ (PA-P04). | V |
| FA-B02 | Yield baseline: `w_i = y_i / Σy` | L18-22 | `baselines.py` | Falls back to equal weight if Σy = 0. | V |
| FA-F01 | Dividend yield: `COALESCE(d_paid.annual, d_declared.annual) / NULLIF(close, 0)` | L1116-1119 | `src/crispdm/features.py` | Uses raw close, not adjusted. | V |
| FA-F02 | Annualized dividend: sum of OPENBB amounts in `[obs−365d, obs]` | L744-781 (`d_paid`) | `features.py` | `COALESCE(adjusted_amount, amount)`. | V |
| FA-F03 | Dividend growth: `current_365 / prior_365 − 1` | L807-830, L1123-1138 | `features.py` | Boundary day counted twice (PA-F02). | V |
| FA-F04 | Payout: `annual / eps_ttm`; FCF payout: `annual / fcf_ttm` (both > 0) | L1282-1283 | `features.py` | EPS per-share basis vs annual OPENBB basis unverified (PA-F03). | V |
| FA-F05 | Momentum (total return): `EXP(Σ daily_total_return over 252 rows) − 1` | L729-732, L1237 | `features.py` | Requires `tr_samples_252 ≥ 252`. | V |
| FA-F06 | Volatility: `STDDEV_SAMP(daily_return over 252) × √252` (price-only log) | L727-728, L1241-1242 | `features.py` | | V |
| FA-F07 | Price-quality median: `percentile_cont(0.5)` over full stored history per security | L888-894 | `features.py` `classify_price_quality` (L559-602) | Full-sample look-ahead (PA-F04). | V |
| FA-F08 | Yield plausibility band: null yield outside `[1e-6, 0.25]` | L214-215, L281-320 | `features.py` | Symptom-level guard for unadjusted reverse splits (PA-F05). | V |
| FA-E01 | Event study abnormal return: `AR = (r + amount/p_prev) − market` on day 0 | L235-240 | `src/crispdm/event_study.py` | Market = equal-weight payers mean (`market_return`). | V |
| FA-E02 | Event drop ratio filter: drop if `amount / p_prev > 0.10` | L223-224 | `event_study.py` | `MAX_EVENT_YIELD = 0.10`. | V |
| FA-E03 | Daily return blanking: `|r| > 0.5` or prior close < 5.0 → NaN | L74-75 | `event_study.py` `daily_returns` | A 2-for-1 split (r ≈ −0.5) is not blanked by `> 0.5` ... boundary; Inferred gap (PA-F06). | V |
| FA-E04 | Winsorization: per-offset quantiles over all events (full sample) | L246-250 | `event_study.py` | Full-sample look-ahead for a historical study (informational). | V |
| FA-N01 | Cross-sectional percentile: `rank(pct=True)`; `high=False` → `1 − rank` | `scoring.py` L93-95 | `src/crispdm/scoring.py` `pct` | Computed per scoring run; not pooled history. | V |
| FA-N02 | Risk-free daily: `(1 + UST_3M/100)^(1/252) − 1`, ffill then bfill | `portfolio.load_risk_free` L615-644 | `portfolio.py` | bfill uses a later yield for early dates (minor, Inferred). | V |
| FA-N03 | Price-series filter: `MIN_PRICE = 1.0 ≤ close ≤ ABSURD_PRICE_HIGH = 1e6`; `ABSURD_PRICE_LOW = 1e-4` | UNIVERSE_SQL L76-84; clean_prices L647-670 | `portfolio.py` | | V |

## 2. Constant Register

| Constant | Value | File | Used by | Tested |
|---|---|---|---|---|
| `MAX_SINGLE_PAYMENT_RATIO` | 1.0 | returns.py L70; portfolio.py; features.py L248 | total return guards | Partial (PA-P06, boundary untested) |
| `MAX_PER_SHARE_DIVIDEND` | 1000.0 | dividend_limits.py L11 | SEC normalize | Yes (populate tests) |
| `MAX_OPENBB_PER_SHARE_DIVIDEND` | 1,000,000.0 | dividend_limits.py L17 | OpenBB normalize, features | Yes |
| `SPLIT_TOLERANCE` | 0.10 | portfolio.py | clean_prices | No (PA-P07) |
| `SPLIT_EVENT_WINDOW_DAYS` | 5 | portfolio.py | clean_prices | No (PA-P07) |
| `SPIKE_THRESHOLD` / `REVERSION_BAND` / `REVERSION_SESSIONS` | 0.50 / 0.20 / 5 | portfolio.py | clean_prices | Yes |
| `ABSURD_PRICE_HIGH` / `ABSURD_PRICE_LOW` | 1e6 / 1e-4 | portfolio.py | clean_prices | Yes |
| `FORWARD_WINDOW_DAYS` | 252 | returns.py L63 | forward returns | Constant only |
| `AMOUNT_TOLERANCE` / `YAHOO_ROUNDING` / `EVENT_WINDOW_DAYS` / `POLYGON_MAX_ERROR` | 0.01 / 0.0005 / 4 / 0.10 | openbb_client.py L270-278 | reconciliation | Yes |
| `MIN_PRICE` (event study) | 5.0 | event_study.py L33 | returns | Yes |
| `MAX_EVENT_YIELD` | 0.10 | event_study.py L36 | event drop | Yes |
| `CLEANING_LOOKAHEAD` | 14 days | backtest.py | prices window | No (PA-P05) |
| `UNRELIABLE_REJECT_SHARE` | 0.20 | portfolio.py | exclude_unreliable | Yes |
| `RECHECK_UNRESOLVED_DAYS` | 7 | populate_dividend_data.py L736 | verdict cache | No |
| `UNDECLARED_HORIZON_DAYS` | 120 | populate_dividend_data.py | projection filter | Yes |
| `PERIODS_PER_YEAR` | 12 | backtest.py | turnover annualization only | — |

## 3. Adjustment Chain (what is applied, where)

| Adjustment | Applied in | Applied to | Not applied in |
|---|---|---|---|
| Split (dividend amount) | `openbb_client._price_basis_adjust` | FMP dividend rows only | yfinance-only path (PA-D14) |
| Split (close price) | `portfolio.clean_prices` | Backtest, dashboard (when split events passed) | `returns.py`, `features.py`, `event_study.py`, `total_return_matrix` standalone, validated baseline path |
| Dividend in total return | `returns.py`, `portfolio.total_return_matrix`, `features.py` | OPENBB rows, `COALESCE(adjusted_amount, amount)` | SEC_XBRL rows (excluded by design) |
| Absurd dividend | `dividend_limits` (1M cap), `MAX_SINGLE_PAYMENT_RATIO` | Feature store, total-return guard | — |

## 4. Open Items (Unknown)

| ID | Item | Type |
|---|---|---|
| FA-U01 | Whether stored `raw.market_data.close` values are split-adjusted for every name (affects FA-P01, FA-F01) | U |
| FA-U02 | Whether `raw.market_data.adjusted_close` is ever populated (documented 100% NULL, not queried in Stage 1A) | A |
| FA-U03 | Whether Yahoo `dividends` are on the split-adjusted basis (code compares `match[1]` to `amount/factor`) | A (0.6) |
| FA-U04 | Coverage basis: OPENBB annual dividend per share vs SEC EPS per share | U |
