# KPI Library and As-Of Rules

Load when: interpreting a KPI, score component, coverage figure or composite
weight, or checking whether a number is point-in-time evidence.

## Evidence and as-of discipline

Every number carries its `as_of_date`, relation and filter. A score is a
cross-sectional percentile rank at one date; a feature is a point-in-time
measurement; a forward return is knowable only after its window closes. A
number without an as-of date is not evidence.

NULL is not zero. `model.features` is deliberately NULL when a denominator is
absent or non-positive. `model.scores.score_coverage` is the share of composite
weight actually measured; a security below `MIN_PRESENT_WEIGHT` is not scored.

## KPI library

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

## Composite and ranking

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

## Interpretation rules

1. Code and tests win over documents; cite the relation, filter and as-of.
2. Use point-in-time data only. A forward-looking statement states its
   assumptions and is not presented as observed data.
3. Never treat NULL as zero. Report coverage and the missing evidence.
4. The composite is a relative rank, not a probability.
5. Separate observed, derived and inferred values. Label the model portfolio,
   style-factor proxies, F-Score coverage and any external KPI.
6. Do not invent a metric, benchmark or source. An unavailable metric is N/A
   with the reason.
7. Weight, universe and acceptance-criteria changes are a
   `business-understanding` decision, not an analysis edit.
