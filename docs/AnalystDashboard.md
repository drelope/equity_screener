# Analyst Dashboard

The analyst dashboard is the read-only reporting surface for the rule-based
dividend score. It turns the ranked universe into a simulated long/short book
and reports performance, risk, positions, factor tilts, research coverage and
standard drafts. It is a research construct, not an account, a backtest with
execution costs, or investment advice.

- Page: `app/views/dashboard.py`
- Analytics: `src/crispdm/portfolio.py`
- Skill: `skills/financial-analysis/SKILL.md`
- Tests: `tests/test_portfolio.py`, `tests/test_dashboard_view.py`,
  `tests/test_financial_analysis_skill.py`, `tests/test_requirements_weights.py`

## Product target

The product target is the seven-tab analyst suite below. It replaces the
earlier Word specification; this section is now the single source of truth.
Optional enhancements are listed separately and are not part of the current
scope.

| Tab | Required content | Status |
|---|---|---|
| Portfolio Dashboard | NAV, returns, exposure, sector allocation | Built. Gross and net are shown as metric cards, not gauges. |
| Performance Analytics | Monthly heatmap; Sharpe, Sortino, Calmar, IR, Omega; drawdown | Built. |
| Risk Monitor | VaR decomposition; stress tests; correlation matrix; limit dashboard | Built. Stress tests are historical worst windows, not scenario shocks. |
| Position Book | 23-position long/short table with P&L, VaR contribution, conviction, F-Score | Built. 15 longs and 8 shorts. |
| Factor Attribution | Factor radar; sector excess-return table; style drift | Partly built. The radar uses score components, not a Fama-French regression. "Sector alpha" is reported as sector excess return versus the book. Style drift waits for two stored rebalance snapshots. |
| Research Pipeline | Kanban (Draft, Final, Uncovered); coverage tracker; catalysts calendar | Built. |
| Reports Center | Morning note, performance report, risk report, IC memo, research note | Built as five deterministic drafts. The IC memo is not AI-generated; no language model is called. This is a deliberate deviation. |

Optional enhancements (not built):

| Enhancement | Blocker or dependency |
|---|---|
| DCF / LBO modeler | Separate valuation scope. |
| Live watchlist with alert thresholds | The warehouse is daily; no real-time price feed. |
| Backtest engine (factor weights over history) | Needs a longer stored score history and a walk-forward design. |
| Export reports as Word | Markdown drafts exist; no Word export. |
| Fund pitch deck | Not started. |
| Sector deep dive | Portfolio-level sector attribution exists; no sector-level tool. |

## Scope and labels

Every tab states the model's as-of date and the caveats that change the
interpretation:

- the book is **simulated**;
- the book is **not live** and no broker or order path exists;
- borrow, financing, slippage and taxes are **excluded**;
- the benchmark is the **equal-weight scored universe**, not a published index;
- factor exposures are weighted score components, **not a Fama-French
  regression**;
- F-Score is **n/a** when any of the nine signals is missing, not zero;
- an IC memo exists only when a **Final** worksheet exists.

## Data sources

| Output | Source | As-of / filter |
|---|---|---|
| Composite, component scores, coverage | `model.scores` | completed-month rebalance date |
| Ranked universe | `model.scores` with `score_coverage >= 0.50` | same date |
| Sector | latest `clean.company_profile` row for the security | profile load order |
| Daily total returns | `raw.market_data` close plus OPENBB `raw.dividend_data` | formation close through latest score date |
| F-Score | `fundamentals.periodic_financials` | two latest `FY` periods filed on or before formation |
| Research status | `analysis.investment_analyses` | latest saved rows |
| Catalysts | OPENBB `raw.dividend_data` ex-dates | next 90 days for held names |

## Model portfolio construction

1. **Universe.** Every security with a published composite on the rebalance
   date and `score_coverage >= 0.50`. Names below the score floor are not ranked.
2. **Rebalance date.** The last score date of the most recent **completed**
   month. A partial current month is not used, so opening the dashboard on a
   different day cannot silently change the book. If no month has completed,
   the earliest score date is used.
3. **Selection.** The top 15 composite scores are long; the bottom 8 are short.
   A name cannot appear in both sleeves.
4. **Sizing.** Base NAV is $100M. The long sleeve is 100% of NAV, equal-weighted
   across 15 names (6.67% each). The short sleeve is 50% of NAV, equal-weighted
   across 8 names (6.25% each). Gross exposure is therefore 150%; net exposure is
   +50%.
5. **Returns.** Daily total return is `(close_t + dividend_t) / close_{t-1} - 1`.
   A dividend is credited on the first price row on or after its ex-date, matching
   `src/crispdm/returns.py`. A short position earns the negative of that return,
   so it pays the dividend through its negative weight.
6. **NAV.** The daily portfolio return is the sum of signed position weights times
   position returns. NAV compounds from the $100M base; drawdown is measured
   against the running peak.
7. **Exclusions.** No transaction costs, borrow, financing, slippage, taxes,
   corporate-action adjustments beyond the stored close and dividend series, or
   intraday execution.

This is a model portfolio, not a walk-forward strategy validation. The score
history currently begins in September 2026, so the dashboard usually shows one
completed rebalance and a short performance window. A longer history is required
before treating any ratio as evidence of skill.

## Conventions

- Returns, weights, drawdowns and VaR are decimal fractions of NAV. Displayed
  money amounts are fraction times $100M.
- Sign convention: long weights and P&L are positive for gains; short weights are
  negative, and a falling price on a short is a gain.
- Annualisation uses 252 trading days. Volatility uses the sample standard
  deviation (`ddof = 1`).
- The risk-free rate is **zero** until a T-bill series is wired in. Sharpe is
  therefore an excess-to-zero ratio, not an excess-over-cash ratio.
- A ratio is shown as `n/a` when its denominator is zero or the sample is too
  short to define it. It is never shown as zero.
- Every metric card or table names its window and observation count.

## Metrics

### Performance Analytics

Let `r_t` be the daily portfolio return over `N` observations.

- **Cumulative return:** `NAV_T / NAV_0 - 1`, compounded daily.
- **Annualised return:** `(1 + cumulative)^(252 / N) - 1`.
- **Annualised volatility:** `stdev(r_t) * sqrt(252)`.
- **Sharpe:** `mean(r_t) / stdev(r_t) * sqrt(252)`, with rf = 0 (see Conventions).
- **Sortino (standard definition):** `mean(r_t) / DD * sqrt(252)`, where the
  downside deviation is `DD = sqrt( (1/N) * sum(min(r_t, 0)^2) )`. The
  denominator uses **all** `N` observations with a target of zero. Sortino is
  `n/a` when no return is negative.
- **Calmar:** annualised return divided by the absolute maximum drawdown over the
  loaded window. Calmar is conventionally computed over three years; a short
  window makes it unstable and it should be read with the observation count.
- **Information ratio:** `mean(r_t - b_t) / stdev(r_t - b_t) * sqrt(252)`, where
  `b_t` is the equal-weight scored-universe return.
- **Omega (threshold 0):** `sum(max(r_t, 0)) / |sum(min(r_t, 0))|`.
- **Hit rate:** share of days with `r_t > 0`. Computed by `performance_metrics`.
- **Drawdown:** `NAV_t / max(NAV_s, s <= t) - 1`. Maximum drawdown is the minimum.
- **Monthly heatmap:** returns compounded within each calendar month. The first
  and last months can be partial and are labelled as such.

These are realised-sample statistics over a short window. They are not
forecasts, confidence intervals, or evidence that the score has predictive power.

### Risk Monitor

Horizon is **one trading day** and confidence is **95%, one-tailed** unless
stated otherwise.

- **Historical VaR 95:** the negative 5th percentile of the daily portfolio
  return series. Expressed as a loss fraction of NAV.
- **Expected shortfall 95:** the mean loss over days at or below the historical
  VaR quantile.
- **Parametric VaR 95:** `1.645 * sigma_p`, where `sigma_p = sqrt(w' Sigma w)` uses
  signed weights `w` and the sample covariance `Sigma` of position returns.
  Zero mean is assumed.
- **Component VaR:** `w_i * (Sigma w)_i / sigma_p * 1.645`. Components sum to
  parametric VaR (Euler decomposition). Hedges contribute negatively.
- **Annualised portfolio volatility:** `sigma_p * sqrt(252)`.
- **Stress tests (historical):** the worst compounded return over 1, 5 and 20
  trading days in the loaded window. These are realised windows, not
  hypothetical shocks. Scenario stresses are listed under gaps.
- **Correlation matrix:** pairwise correlation of daily position returns over the
  same window.
- **Limit dashboard:** illustrative research limits of 200% gross, 75% absolute
  net, 10% single name and 35% single sector. A breach is displayed as a breach.
  The limits are not regulatory or investment-policy limits.

*Known limitation:* the covariance matrix is computed pairwise over whatever
history each name has. With short or uneven histories the matrix may not be
positive semi-definite, and parametric VaR can be misstated. Parametric VaR should
be read alongside historical VaR until the window is complete for every held name.

### Position Book

- Weight and notional are signed fractions of NAV; notional is weight times
  $100M.
- P&L is signed weight times total return times $100M. A short with a positive
  return reduces P&L.
- Component VaR is the position's contribution to parametric VaR.
- **F-Score** is the canonical nine-signal Piotroski score, computed from the two
  latest filed fiscal years. Missing inputs make the score `n/a`, not a failure.
- **Conviction** is a coarse label derived from the rule below. It is not a
  recommendation and does not replace the research worksheet.

Conviction rule, applied in order. Let `strength = score` for a long and
`1 - score` for a short, `coverage` be score coverage, and `F` be the F-Score
when it is measured:

1. If `strength >= 0.80` and `coverage >= 0.75`: **High**, unless `F` is measured
   and `F < 5`, in which case **Medium**.
2. Else if `strength >= 0.60` and `coverage >= 0.50`: **Low** when `F` is measured
   and `F < 3`, otherwise **Medium**.
3. Otherwise **Low**.

An unmeasured F-Score is treated as missing evidence, not as bad evidence, so it
never lowers a label on its own.

### Factor Attribution

- **Factor exposure:** weighted average of each score component in the long and
  short sleeves. This is a style proxy, not a Fama-French regression.
- **Sector weights vs scored universe:** gross weight by sector in the book
  compared with the equal-weight scored universe's sector share.
- **Sector P&L and excess return:** signed P&L by sector, and the weighted
  position return minus the book return. It measures within-book selection
  against the book, not a published sector index.
- **Style drift:** requires at least two completed rebalance snapshots. Until the
  warehouse stores them, the tab says so instead of drawing a trend from one point.

### Research Pipeline

- **Kanban:** Draft, Final and Uncovered positions from
  `analysis.investment_analyses`, matched by ticker. A held name with no worksheet
  row is Uncovered.
- **Coverage tracker:** positions, gross notional and F-Score completeness by
  sector.
- **Catalysts:** upcoming OPENBB ex-dividend dates for held names over the next
  90 days.

### Reports Center

The page generates five deterministic Markdown drafts: morning note, performance
report, risk report, IC memo and research note. The IC memo is only written as an
IC memo when a Final worksheet exists; otherwise the page says none exists. No
language model is called. Numbers come from the loaded context and narrative is
templated.

## Reporting standard

Every tab must show:

1. the as-of date and the rebalance date;
2. the sample window and observation count;
3. units and sign convention in the column or card label;
4. the scope caveats from **Scope and labels**;
5. `n/a` where a value is undefined, never a silent zero;
6. no hard-coded narrative numbers; all figures come from the loaded context.

## Gaps against industry-standard KPIs

These measures are common in long/short hedge-fund reporting. None is implemented
yet, and each is listed with the reason.

| Measure | Why it matters | Blocker |
|---|---|---|
| Sharpe over T-bill excess return | Comparability with fund reporting | No risk-free series in the warehouse. |
| Market beta and alpha vs a benchmark | Separates exposure from selection | No benchmark index series stored; only the equal-weight universe. |
| Beta-adjusted net exposure | Standard net exposure measure for a long/short book | Requires beta (above). |
| Explicit tracking error | Active risk, reported beside IR | Computed inside IR but not displayed. |
| Turnover | Realism of the rebalance | Only a single snapshot; no trade history. |
| Liquidity: days-to-liquidate and ADV participation | Capacity and exit risk | Volume is not loaded by the portfolio queries. |
| Transaction cost and borrow cost | Net-of-cost returns | No cost or borrow data. |
| Scenario stress (for example, market -10%, sector shock) | Forward-looking tail risk | Not implemented. |
| Concentration: top-5 weight, Herfindahl index | Diversification | Not implemented; computable from the book. |
| Drawdown duration, skew and kurtosis | Shape of the tail and recovery | Not implemented; computable from NAV. |

## Reproduce

```bash
python -m scripts.score_rank --prune-superseded
streamlit run app/streamlit_app.py
```

Open **Analyst dashboard** in the navigation, or use the `dashboard` URL path.
The page uses cached read-only queries via `app.ui.query`.

## Verification

```bash
ruff check .
ruff format --check .
pytest -q tests/test_financial_analysis_skill.py tests/test_portfolio.py \
  tests/test_dashboard_view.py tests/test_requirements_weights.py
```

The full suite (`pytest -q`) also runs `tests/test_streamlit_app.py`, which opens
every registered page through the app shell. It is slower and is not part of the
targeted command above.

Last verified on 2026-10-24: `ruff check .` and `ruff format --check .` pass, and
the four targeted files pass (30 tests). The full suite passed (1538 tests) on
the same day.

## Known limitations

- Score history is short; one completed monthly rebalance does not validate a
  strategy.
- F-Score coverage is incomplete because annual fundamentals are not available
  for every ranked name. Missing scores are shown as `n/a`.
- The equal-weight universe benchmark is not a published index and carries the
  same data gaps as the portfolio.
- The security master is current, not point-in-time, so the model can inherit
  survivorship bias.
- The short book assumes the names can be borrowed; no borrow availability or
  cost data exists in the warehouse.
- Daily prices are not adjusted by the provider (`adjusted_close` is NULL), so
  total return depends on the stored dividend series and the ex-date mapping.
- Corporate actions other than cash dividends are not modelled.
- Parametric VaR uses a pairwise covariance matrix that can be unstable with
  short or uneven histories.
