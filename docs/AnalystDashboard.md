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
| Risk-free rate | `raw.macro_series`, `UST_3M` (percent p.a.) | daily, compounded; forward-filled |

## Model portfolio construction

1. **Universe.** Every **common stock** (`reference.securities.security_type =
   'common_stock'`) with a published composite on the rebalance date and
   `score_coverage >= 0.50`. Names below the score floor are not ranked.
   Preferreds, bonds, derivatives, futures and the ambiguous `equity` and
   `other` types are excluded because the dividend score is not a valid
   ranking for them.
   The formation-date close must be at least **$1** (`MIN_PRICE`). Below that,
   the warehouse holds corrupt closes (for example 0.0006 followed by 1.50), and
   a name without a close on the formation date is excluded.
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

This is a model portfolio. The Portfolio and Risk tabs describe **one** book built
from the latest completed month, so their performance window is short. The
Performance tab also shows the walk-forward backtest over the stored history
(see the next section). Scores are stored point-in-time for 93 month-ends from
2019-01-31 to 2026-08-31, plus the daily scores from September 2026. No single
ratio is evidence of skill; the backtest is the basis for any such claim, with its
limits. The historical scored universe grows from 1,760 names in 2019 to about
2,800 in 2026. Part of that growth is real coverage; part is identity fragmentation
(see Survivorship and identity below), so early rebalances use a narrower universe
than the market.

## Walk-forward backtest

`src/crispdm/backtest.py` chains the model book across all stored month-ends.
At each rebalance date the book is built from that date's scores, using the same
selection and sizing as the dashboard, and held until the next rebalance date.

- **Timing.** A holding period earns returns strictly after its formation close
  and through the next rebalance close. A name is never credited with the return of
  the day its score was known.
- **Costs.** None. Turnover is reported, so costs can be judged against it.
- **Cash.** A period with too few scored names is held in cash and recorded.
- **Benchmark.** The equal-weight scored universe at the same formation date.
- **Schedule.** The last score date of each calendar month, plus the newest date.

Run: `python -m scripts.backtest` (about four minutes). It writes the daily series,
the per-period table and the metrics to `artifacts/backtests/` (gitignored). The
Performance tab shows the newest complete run.

**Price filter (`stale_reversal_absurd_split_unreliable_v5`).** Applied per security to every
holding period before returns are computed (`src/crispdm/portfolio.py`, `clean_prices`):

- a close above 1e6 or below 1e-4 is a unit or feed error and is rejected
  (1,924 such daily moves of 40% or more in the warehouse); a security with no
  usable print in the window is blanked, so it earns no return rather than noise;
- a print with zero volume is stale and is rejected;
- a close more than 50% away from the last accepted close is a spike; it is
  rejected if a later accepted print, within 5 sessions, returns to within 20% of
  the last accepted close;
- a rejected print is replaced by the last accepted close, so its return is zero
  and any dividend on that day is kept;
- a move that persists is kept, because it may be a real event;
- a missing volume is unknown, not zero, and is never rejected for volume;
- prices are read 14 calendar days past each period end, so a spike near the end
  can be confirmed. Returns are taken only up to the period end;
- the universe requires a formation close between 1e-4 and 1e6, so an absurd
  print cannot enter the book at formation.
- **Unreliable histories are excluded.** A security whose cleaned window rejects
  more than 20% of its prints (`UNRELIABLE_REJECT_SHARE`, a judgment call), or
  whose window has no usable print, is removed from the scored universe for that
  period. It is not kept with a cleaned series. The backtest records how many
  securities were excluded (241 over the run). The dashboard applies the same
  rule to its current book and benchmark.

**Splits.** Split history comes from FMP (`/stable/splits`), fetched by
`scripts/fetch_fmp_splits.py` into `artifacts/corporate_actions/fmp_splits.csv`
(gitignored). The fetch covered all 4,101 common-stock tickers with prices, with
no failures, and gave 7,400 events mapped to 2,124 identities. Coverage runs back
to 2003 for large names. A split is applied only when the warehouse price shows
the matching jump: the one-session move on the event date must be within 10% of
the reported ratio (denominator over numerator), and the event must fall within
5 days of a price. Earlier prints are then scaled, so the split day has no return.

Why the check comes first. On a 15-name sample, 3 of 67 FMP events showed their
jump in the warehouse prices, 44 showed none (most of the warehouse is already
adjusted by the provider), and 20 fell outside the price history. Applying every
FMP event blindly would have scaled prices that were already right. Matching to
the price jump is what prevents that. Some histories remain unusable even after
the check: WHLR's closes sit near 20,000 to 30,000 after dozens of unadjusted
reverse splits, and no single event matches, so that history is not adjusted.

Effect. The filter rejected 199,017 prints and applied 145 split adjustments.
On the short side it removed the bad prints that had produced the largest losses
(PNYG alone added about +0.48 of cumulative contribution across two periods, and
the WHLR history added the -21% day that the absurd-price fix and the usable-print
rule now remove). Longs changed by about +0.01.

Results, 2019-01-31 to 2026-10-23, 93 rebalances, costs excluded:

| Run | Cumulative | Sharpe | Max drawdown | Information ratio |
|---|---|---|---|---|
| Before V0092, unfiltered | -55.4% | -0.63 | -76.9% | -0.92 |
| After V0092, unfiltered | +175.6% | 0.45 | -72.2% | -0.00 |
| After V0092, price filter v1 | +859.1% | 1.06 | -58.6% | 0.52 |
| After V0092, price filter v2 (adds absurd-price rule) | +732.9% | 0.96 | -58.2% | 0.47 |
| After V0092, filter v3 (adds FMP split confirmation) | +754.4% | 0.97 | -57.1% | 0.48 |
| After V0092, filter v4 (adds usable-print and formation-bound rules) | +658.2% | 0.95 | -57.7% | 0.43 |
| After V0092, filter v5 (excludes unreliable histories) | +497.6% | 0.84 | -59.2% | 0.36 |

The equal-weight universe (reliable names only) returns +69% over the same window.
The filtered figures are still not a finding about the score, for three reasons. Some histories are
unusable even after the checks (WHLR), and the survivor-only history remains. Short
squeezes are real and kept (AMC, January 2021, +301% in one session), so their
short-side losses are not limited by the construction. The largest remaining
losses are the 2020 COVID drawdown and the January 2021 squeeze, both real events.

**Event risk.** That -14.4% day came from one short, ADAMG, whose price moved from
8.72 to 25.33 and stayed there, on normal volume. The pattern fits a corporate
event rather than a bad print. The warehouse cannot confirm the event, so the
result is kept. The short sleeve carries event risk that the equal-weight
construction does not limit.

## Survivorship and identity

Two defects limit what the backtest can say. Both were measured on 2026-10-24
against the warehouse; neither has been repaired.

**1. No delisted securities before 2026.** In `raw.market_data`, 6,423 of 6,424
securities end their price history in 2026 (one ends in 2025, none earlier). The
price source returns only names trading now, so a company that stopped trading
before 2026 is absent from every historical date. This cannot be fixed in code;
it needs a delisting history from a data provider. Survivorship bias is therefore
structural in the backtest, and its direction is mixed. Long-book returns are
overstated, because failed longs are missing. Short-book returns are understated,
because the big gains on shorts that later delisted are missing. The net effect
on the long/short result is not known.

**2. Identities split a company's history.** `reference.securities.security_id`
is a UUID derived from ticker, CIK, security type and the dividend flag
(`scripts/populate_reference_tables.py`). When any of those change, the reseed
creates a new identity with no price history and marks the old one inactive,
because the old one still has child rows. Measured:

- 6,618 active common-stock identities; 1,999 have any price row, and 4,619 have
  none.
- January 2019: 2,526 common-stock companies (by CIK) have a price. For 982 of
  them (39%), only a superseded identity carries the price, so the backtest,
  which scores active identities, never sees them.
- Reseeds that created most of the new identities ran on 2026-09-22, 09-25,
  10-06, 10-07 and 10-08.

**Fixed (V0092, applied 2026-10-24).** A security's identity is now
`(cik, ticker, security_type)`. `dividend` is an attribute, so a flag flip updates
the row in place. The migration merged the 2,787 split groups: the row with the
most price history keeps its `security_id`, the childless twin is removed, and
the children of the removed rows are re-pointed. Measured after the migration:

- one identity index, `ux_security_cik_ticker_type`; no duplicate identities;
- companies (by CIK) unchanged at 8,169; active identities unchanged at 10,746;
- active common-stock identities with prices: 1,999 before, 3,867 after;
- the current universe on 2026-10-23 is unchanged at 1,891 names. The change is
  in history: the winners carry prices and features back to 2019.

Still open:

- 2,751 active common-stock identities have no price rows. For 540 of them, the
  same CIK has a priced identity under a different ticker or security type.
  Those are classification or ticker flips, which V0092 deliberately does not
  merge, because a security type can be a real distinction.
- Price quality in the warehouse is not clean. A stale print can look like a
  real move: PNYG printed 0.90, then 4.99 on near-zero volume for four sessions,
  then 0.80. The backtest is sensitive to such prints (see the next section).

## Conventions

- Returns, weights, drawdowns and VaR are decimal fractions of NAV. Displayed
  money amounts are fraction times $100M.
- Sign convention: long weights and P&L are positive for gains; short weights are
  negative, and a falling price on a short is a gain.
- Annualisation uses 252 trading days. Volatility uses the sample standard
  deviation (`ddof = 1`).
- The risk-free rate is the **3-month Treasury yield** (`UST_3M` in
  `raw.macro_series`, percent per annum), converted to a compounded daily rate
  over 252 days. If the series does not cover every return date, Sharpe falls
  back to a zero rate and the Performance tab says so.
- A ratio is shown as `n/a` when its denominator is zero or the sample is too
  short to define it. It is never shown as zero.
- Every metric card or table names its window and observation count.

## Metrics

### Performance Analytics

Let `r_t` be the daily portfolio return over `N` observations.

- **Cumulative return:** `NAV_T / NAV_0 - 1`, compounded daily.
- **Annualised return:** `(1 + cumulative)^(252 / N) - 1`.
- **Annualised volatility:** `stdev(r_t) * sqrt(252)`.
- **Sharpe:** `mean(r_t - rf_t) / stdev(r_t - rf_t) * sqrt(252)`, where `rf_t` is
  the daily risk-free return (see Conventions).
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
  Zero mean is assumed. `Sigma` is estimated on a **common window**: only dates on
  which every held name has a return. The window length is reported with the risk
  metrics. A pairwise estimate over uneven histories is not guaranteed positive
  semi-definite, so it is not used.
  **Reliability flag:** a sample covariance of `n` names is full rank only with
  more than `n` common dates. When the window has `n` dates or fewer, the Risk
  Monitor shows a warning and parametric VaR should not be used. Passing the
  flag is necessary, not sufficient: a window of a few times `n` is still noisy.
- **Component VaR:** `w_i * (Sigma w)_i / sigma_p * 1.645`. Components sum to
  parametric VaR (Euler decomposition). Hedges contribute negatively.
- **Annualised portfolio volatility:** `sigma_p * sqrt(252)`.
- **Stress tests (historical):** the worst compounded return over 1, 5 and 20
  trading days in the loaded window. These are realised windows, not
  hypothetical shocks. Scenario stresses are listed under gaps.
- **Correlation matrix:** correlation of daily position returns over the same
  common window as `Sigma`.
- **Limit dashboard:** illustrative research limits of 200% gross, 75% absolute
  net, 10% single name and 35% single sector. A breach is displayed as a breach.
  The limits are not regulatory or investment-policy limits.

*Known limitation:* the common window is as short as the newest held name's
history. A short window makes `Sigma` noisy, so parametric VaR should be read
alongside historical VaR and the reported window length.

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
  tests/test_dashboard_view.py tests/test_requirements_weights.py tests/test_backtest.py
```

The full suite (`pytest -q`) also runs `tests/test_streamlit_app.py`, which opens
every registered page through the app shell. It is slower and is not part of the
targeted command above.

Last verified on 2026-10-24: `ruff check .` and `ruff format --check .` pass. The
targeted files pass: 39 tests across the skill, portfolio, requirements and backtest
files, and 7 dashboard tests, including the render with the backtest section. The
full suite passed (1540 tests) before the $1 price floor, the backtest and the
dashboard section were added; it has not been rerun since.

## Known limitations

- The Portfolio and Risk tabs show one book. The backtest on the Performance tab
  reads the newest saved run in `artifacts/backtests/`; it does not recompute on
  page load, so it can lag the warehouse until `python -m scripts.backtest` is run
  again. Its result is negative on this history.
- Survivorship and identity: see the section below. In short, the price source
  has no delisted securities before 2026, and each company's history is split
  across identities, so the backtest universe is a subset of the market.
  Filing-date point-in-time for fundamentals is not yet verified.
- F-Score coverage is incomplete because annual fundamentals are not available
  for every ranked name. Missing scores are shown as `n/a`.
- The equal-weight universe benchmark is not a published index and carries the
  same data gaps as the portfolio.
- The security master is current, not point-in-time, so the model can inherit
  survivorship bias (see below).
- The short book assumes the names can be borrowed; no borrow availability or
  cost data exists in the warehouse.
- Daily prices are not adjusted by the provider (`adjusted_close` is NULL), so
  total return depends on the stored dividend series and the ex-date mapping.
- Corporate actions other than cash dividends are not modelled.
- `security_type` is the current classification, not point-in-time, so a
  historical rebalance uses today's label.
- Parametric VaR is estimated on the common window of held names, which is only
  as long as the newest held name's history.
