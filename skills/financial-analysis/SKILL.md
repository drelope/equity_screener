---
name: financial-analysis
description: "Use when validating a dividend investment, interpreting KPIs, scores, rankings or coverage, assessing model-portfolio risk, or preparing the 7-tab analyst dashboard and its reports (morning note, performance, risk, IC memo, research note). Do not use for score-weight policy (financial-scoring), the 18-step worksheet (investment-analysis), data pipelines, or the ML gate."
version: 1
risk: read
owner: analysis
entrypoint: none  # none|fixed|list
tags: [analysis, kpi, risk, reporting, dashboard]
---

# Financial Analysis

Turn point-in-time KPIs, the rule-based score and portfolio risk into an
evidence-backed investment view and a standard report. This skill is the
analyst-facing layer; it does not change the score and it does not write the
warehouse.

## Objective

- Validate a dividend investment against business quality, earnings quality,
  balance-sheet strength, valuation and the variant perception.
- Explain what the composite and its components measure, how much evidence is
  behind them and what they do **not** mean.
- Manage risk explicitly: decompose it, stress it, size it and define the kill
  switch.
- Communicate the result in a repeatable form that separates observed data,
  derived metrics, assumptions and open questions.

## When to use / when not to use

Use when:

- validating a candidate security or explaining a score, rank or coverage move;
- interpreting a KPI, a component percentile or a model-portfolio risk figure;
- reviewing the analyst dashboard's portfolio, performance, risk, position,
  factor, research-pipeline or reports tabs;
- preparing a morning note, performance report, risk report, IC memo or
  research note;
- checking whether a recommendation has the evidence and risk work it needs
  before it is saved as Final.

Do not use when:

- the task is changing weights, the composite, rankings or thresholds
  (`financial-scoring`);
- the task is filling or saving the 18-step worksheet (`investment-analysis`);
- the task is source acquisition, feature construction or schema change
  (`data-acquisition`, `data-transformation`, `data-storage-schema`);
- the task is the walk-forward model gate (`modeling-evaluation`);
- the task is a broker integration, live order or real portfolio book; those
  are out of scope.

## Content: KPI, validation, risk and reporting framework

### Evidence and as-of discipline

Every number carries its `as_of_date`, relation and filter. A score is a
cross-sectional percentile rank at one date; a feature is a point-in-time
measurement; a forward return is knowable only after its window closes. A
number without an as-of date is not evidence.

NULL is not zero. `model.features` is deliberately NULL when a denominator is
absent or non-positive. `model.scores.score_coverage` is the share of the
composite weight that was actually measured; a security below
`MIN_PRESENT_WEIGHT` is not scored at all.

### KPI library

| KPI | Definition | Repo source / status | Decision use |
|---|---|---|---|
| Dividend yield | annualised dividend / price | `model.features.dividend_yield`; scored | Income, but a high yield is not safety |
| Dividend coverage | earnings available to dividends / dividends | `model.features.dividend_coverage`; scored | Sustainability; falling coverage is a warning |
| FCF payout | dividends / free cash flow | `model.features.fcf_payout`; scored inverted | Lower is safer; negative FCF is a red flag |
| Interest coverage | EBIT / interest expense | `model.features.interest_coverage` | >3x adequate; stress the denominator |
| Net debt / EBITDA | net debt / EBITDA | `model.features.net_debt_to_ebitda` | Leverage and refinancing risk |
| Current ratio | current assets / current liabilities | `model.features.current_ratio` | Liquidity buffer |
| Gross margin | (revenue − COGS) / revenue | `model.features.gross_margin` | Pricing power; compare trend and peers |
| Operating margin | operating income / revenue | `model.features.operating_margin` | Fixed-cost leverage and scalability |
| Net margin | net income / revenue | `model.features.net_margin` | Bottom-line profitability |
| FCF growth | year-over-year change in FCF | `model.features.fcf_growth` | Cash-engine growth and accrual risk |
| Cash conversion | operating cash flow / net income | `model.features.cash_conversion` | Earnings quality |
| Earnings yield | earnings / price | `model.features.earnings_yield`; scored | Valuation |
| FCF yield | free cash flow / price | `model.features.fcf_yield`; scored | Cash-based valuation |
| Price / book | price / book value | `model.features.price_to_book`; scored inverted | Valuation cross-check |
| Momentum | 252d and 63d total return | `model.features`; scored | Appreciation, not fundamentals |
| Volatility | 252d realised volatility | `model.features.volatility_252d`; scored inverted | Risk input |
| ROIC | NOPAT / invested capital | external FMP/autofill only; **not** a model feature or score input | Quality cross-check when available |
| Piotroski F-Score | canonical 9 binary tests | dashboard-derived from `fundamentals.periodic_financials`; coverage-aware | Quality screen, never a substitute for analysis |
| Sharpe / Sortino / Calmar / IR / Omega | return and drawdown ratios | dashboard-derived from the model portfolio | Performance context, not a forecast |
| VaR / CVaR | historical-simulation loss quantile | dashboard-derived from the model portfolio | Risk sizing; method and window must be stated |
| Factor exposures | size, value, quality, momentum, low volatility, investment | dashboard-derived style proxies | Portfolio tilt; **not** a Fama-French regression |

`docs/FinancialAnalyst.md` is a partial reference: it defines six useful KPIs
and stops at section 3.1. Do not treat its missing sections, unsourced
benchmarks or aspirational dashboard rows as implemented facts.

### Composite and ranking

The composite is the weighted mean of the measured components, renormalised
over the available weight:

| Component | Weight |
|---|---|
| `dividend_income_score` | 1/3 (33.33%) |
| `sustainability_score` | 4/15 (26.67%) |
| `appreciation_score` | 1/5 (20.00%) |
| `risk_score` | 2/15 (13.33%) |
| `valuation_score` | 1/15 (6.67%) |

`legal_rights_score` is retired from the composite; the column remains NULL.
`MIN_PRESENT_WEIGHT` is 0.50, `score_coverage` is measured against the baseline
weights, and the regime layer only changes the blend after a security has
cleared the baseline floor. `model.predictions` thresholds the composite; it
is a relative rank, not a calibrated probability.

### Investment validation checklist

1. **Business quality** — how the company earns money, its moat, margin trend
   and capital intensity. Use ROIC only when a sourced value exists.
2. **Earnings quality** — cash conversion, accruals, GAAP vs non-GAAP, one-off
   items and working-capital direction.
3. **Balance sheet** — net debt/EBITDA, interest coverage, current ratio,
   maturity wall and refinancing access.
4. **Dividend safety** — coverage, FCF payout, growth, dividend history and
   legal/economic rights from the worksheet.
5. **Valuation** — earnings yield, FCF yield, P/B, DCF/analyst target where
   sourced; state the assumptions and margin of safety.
6. **Expectations** — consensus vs the analyst's variant perception, with at
   least three evidence lines.
7. **Base rate** — historical analogs and the measured forward-return sample,
   with sample size and caveats.
8. **Catalysts and kill switch** — what changes the view, when, and what
   invalidates the thesis.

### Risk management

Decompose risk into business, valuation, balance-sheet, macro, regulatory and
liquidity risk, then add concentration and correlation at the portfolio level.
For the model portfolio, report gross and net exposure, historical VaR/CVaR,
component VaR, stress-window returns, the correlation matrix and every limit
breach. Position sizing follows the risk score and the loss the thesis can
tolerate; no position is sized from conviction alone.

The model portfolio is a research backtest, not a live book. It excludes
borrow, financing, slippage, taxes and execution. Its selection is
point-in-time, but it is still exposed to survivorship bias in the current
security master.

### Communication and reports

Every report states the as-of date, the universe, the data source and the
simulation/label caveats. The investment view uses:

- thesis: at most three sentences;
- recommendation: Buy / Add / Hold / Trim / Sell, or "no call";
- variant perception: consensus vs the analyst's view;
- risk summary and position sizing;
- scenario table with probabilities summing to 100;
- confidence: High / Medium / Low with the data-quality, forecast,
  sensitivity and conviction reasons;
- sources and open questions.

The analyst dashboard has seven required tabs:

1. **Portfolio Dashboard** — model NAV, return, gross/net exposure, sector
   allocation and top/bottom positions.
2. **Performance Analytics** — monthly heatmap, Sharpe/Sortino/Calmar/IR/Omega
   and drawdown.
3. **Risk Monitor** — VaR/CVaR, component VaR, stress tests, correlation matrix
   and limit dashboard.
4. **Position Book** — 23-position long/short table with P&L, VaR
   contribution, model conviction and F-Score coverage.
5. **Factor Attribution** — style-exposure radar, sector weights vs the
   equal-weight scored universe, sector contribution and style drift when at
   least two completed rebalances exist (otherwise an explicit unavailable
   state).
6. **Research Pipeline** — kanban-style Not analysed/Draft/Final board,
   coverage tracker and ex-dividend catalyst calendar.
7. **Reports Center** — morning note, performance report, risk report, IC memo
   and research note, downloadable as Markdown.

An IC memo is generated only from a saved **Final** worksheet. A Draft may be
summarised, but it is labelled Draft and is not an investment-committee memo.
Optional local-LLM text is a draft aid; it never supplies a number and never
saves a recommendation.

## Inputs

| Kind | Name | Required | Notes |
|---|---|---|---|
| Env | `DATABASE_URL` | yes | Presence only; never print the value. |
| Table | `model.features` | yes | Point-in-time KPI inputs. |
| Table | `model.scores`, `model.rankings` | yes | Composite, coverage and rank. |
| Table | `model.current_predictions` | no | Thresholded rank; never a probability. |
| Table | `model.forward_returns` | no | Base-rate and analog evidence. |
| Table | `fundamentals.periodic_financials` | no | F-Score and reported fundamentals. |
| Table | `analysis.investment_analyses` | no | Final/Draft worksheets and recommendations. |
| Table | `raw.market_data`, `raw.dividend_data` | no | Model-portfolio total returns. |
| Table | `raw.macro_series` | no | Risk-free rate, VIX and benchmark context. |
| Doc | `docs/AnalystDashboard.md` | yes | Dashboard methodology and limits. |
| Doc | `docs/InvestmentAnalysisWorkflow.md` | yes | Worksheet and Final gate. |
| Doc | `docs/FinancialAnalyst.md` | no | Partial KPI reference; not authoritative. |
| Command | `python -m scripts.score_rank` | no | Read-only context; run only via `financial-scoring`. |

## Procedure

1. Run the preflight from `SYSTEM.md`.
2. Frame the question: security or model portfolio, decision, horizon and
   as-of date. Name the universe and the benchmark.
3. Load the point-in-time evidence and record coverage/freshness. Stop if the
   as-of date is stale or the security is below the score floor.
4. Decompose the composite into its five components; state the weight of each
   and the coverage. Explain a score move as a component and universe move,
   not as a forecast.
5. Work the investment-validation checklist. Mark each item observed, derived,
   inferred or unavailable.
6. Work the risk decomposition and the portfolio limits. Run VaR, stress and
   correlation checks where the model portfolio is in scope.
7. Form the view: variant perception, scenarios, base rate, catalysts and kill
   switch. Do not record a call while any of these is missing.
8. Write the report in the standard structure. Use the dashboard for the
   quantitative tables and the worksheet for the qualitative record.
9. Attach sources, as-of dates, confidence reasons and open questions.
10. Hand off writes: score policy to `financial-scoring`, worksheet/Final to
    `investment-analysis`, data gaps to the owning data skill.

## Analysis rules

1. Code and tests win over documents; cite the relation, filter and as-of for
   every quantitative claim.
2. Use point-in-time data only. A forward-looking statement states its
   assumptions and is not presented as observed data.
3. Never treat NULL as zero. Report coverage and the missing evidence.
4. The composite is a relative rank, not a probability. Never call
   `model.predictions` a calibrated forecast.
5. No recommendation without a risk decomposition, position-sizing implication
   and kill switch.
6. Separate observed, derived and inferred values. Label the model portfolio,
   style-factor proxies, F-Score coverage and any external KPI.
7. Do not invent a metric, benchmark or source. An unavailable metric is N/A
   with the reason.
8. Do not execute trades, size a real book, assume borrow/financing, or write
   `market.*`. This skill is read-only.
9. Low confidence requires a written note; scenario probabilities must sum to
   100; the thesis is at most three sentences.
10. Weight, universe and acceptance-criteria changes are a
    `business-understanding` decision, not an analysis edit.

## Outputs

- A score/rank/coverage explanation with component and evidence attribution.
- An investment view with validation checklist, variant perception, scenarios,
  risk decomposition, sizing implication and kill switch.
- The 7-tab analyst dashboard and its Markdown reports.
- No warehouse writes. A Final recommendation is saved through
  `investment-analysis`.

## Verification

Pass when:

- `tests/test_financial_analysis_skill.py` confirms this skill has the
  trigger, objective, process, content, rules and all seven tab names;
- `tests/test_portfolio.py` passes the pure return, risk, F-Score and report
  calculations;
- `tests/test_dashboard_view.py` confirms the seven tabs, model-portfolio
  label, empty states and report registry;
- `tests/test_requirements_weights.py` confirms the documented weights and UI
  caption match `src/crispdm/scoring.WEIGHTS`;
- `tests/test_scoring.py`, `tests/test_analysis_schema.py` and
  `tests/test_workflow_doc.py` pass when the relevant contract moved;
- every displayed metric has a source and as-of, and unavailable data is N/A
  with a reason;
- the composite is never described as a probability and the model portfolio is
  never described as live or investable.

```bash
ruff check .
ruff format --check .
python -m pytest -q tests/test_financial_analysis_skill.py tests/test_portfolio.py \
  tests/test_dashboard_view.py tests/test_requirements_weights.py
```

## Failure handling

- Stale or missing as-of data: stop; report the latest date and the affected
  table. Do not backfill by hand.
- Coverage below `MIN_PRESENT_WEIGHT`: do not score or rank the security; report
  the coverage and the missing components.
- A component is all NULL: report the upstream gap; do not substitute a
  constant.
- A report would need an unavailable metric: show N/A and the reason; do not
  infer a number from a peer or a narrative.
- No Final worksheet: no IC memo; show the Draft status or "no call".
- The model portfolio is requested as live performance: stop and relabel it as
  a simulated research backtest.
- The documented weights disagree with `scoring.py`: code wins; route the
  documentation fix to `business-understanding` before quoting weights.
- The local LLM returns a number or a recommendation: discard the generated
  text; only deterministic facts are allowed.

## Source of truth

- `src/crispdm/scoring.py`
- `src/crispdm/regime.py`
- `src/crispdm/returns.py`
- `src/crispdm/portfolio.py`
- `app/views/dashboard.py`
- `app/analysis_schema.py`
- `docs/AnalystDashboard.md`
- `docs/InvestmentAnalysisWorkflow.md`
- `docs/requirements.md`
- `docs/FinancialAnalyst.md` (partial reference only)

## Runner

- **Mode:** Follow this skill's procedure. The deterministic runner only executes allowlisted fixed entrypoints; this skill has none.
- **Confirmation:** This skill is `read`; it must not write the warehouse. Any write is handed to a `write` skill.

## Preflight

- [ ] Read `SYSTEM.md` and confirm this skill owns the task.
- [ ] `git status --short` reviewed (note exceptions if any).
- [ ] `python -m scripts.migrate --check` exits 0 if the task touches the database or schema.
- [ ] Required environment variables present by name only (never print values). Check `SEC_USER_AGENT` if calling SEC.
- [ ] No pipeline lock held / no conflicting run in progress if executing `run_full_etl`.
- [ ] Scope narrowed to the smallest change that satisfies the request.
- [ ] Confirm the as-of date, universe, benchmark and data freshness.

## Handoffs

- **Weight/universe/acceptance-criteria change:** route to `business-understanding` with the proposed rule and evidence.
- **Score mechanics, re-scoring or threshold change:** route to `financial-scoring`.
- **Worksheet, Final save or recommendation gate:** route to `investment-analysis`.
- **Missing/dirty source data:** route to `data-acquisition` with coverage gaps and tables.
- **Feature or fundamentals defect:** route to `data-transformation`.
- **DB/schema drift:** route to `data-storage-schema` with `migrate --check` output and affected tables.
- **Freshness/health check:** route to `observability-nightly-verification` with `audit.nightly_runs`/`audit.nightly_checks`.
- **Model/label gate:** route to `modeling-evaluation`.
- **Security/secret risk:** route to `security-compliance` (do not share secret values).
- **Dashboard UI implementation:** follow the `developing-with-streamlit` skill; release through `deployment-release`.

## Stop conditions

- [ ] Task is outside this skill's scope (see "Do not use when").
- [ ] A quantitative claim has no relation, filter or as-of.
- [ ] A score or rank is requested for a security below `MIN_PRESENT_WEIGHT`.
- [ ] A recommendation is requested without risk decomposition, sizing and a kill switch.
- [ ] A Draft is presented as an IC memo or a Final recommendation.
- [ ] The model portfolio is presented as live, investable or free of costs.
- [ ] A metric has no definition or its source is unavailable and would be invented.
- [ ] A weight/universe change is requested inside this skill.
- [ ] Action would write `market.*`, delete reference rows, or release a ticker conflict without its dedicated confirmed command.
- [ ] Secret would be printed, logged, or committed.
- [ ] Unexpected `git status` changes in the scoped area.

## Evidence required

- **Commands:** argv list, cwd, exit codes, timestamps.
- **State:** tables/rows read and the as-of date; affected `audit.nightly_runs`/`audit.nightly_checks` when relevant.
- **Findings:** relation/filter/as-of for every quantitative claim; component and coverage attribution for score claims.
- **Reports:** report type, generated file/artifact path, model-portfolio or worksheet source, and the label/caveats shown.
- **Handoffs:** target skill + reason + evidence attached.
