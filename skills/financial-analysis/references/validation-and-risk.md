# Validation and Risk

Load when: working an investment-validation checklist, decomposing portfolio or
security risk, setting a sizing implication, or defining a kill switch.

## Investment validation checklist

1. **Business quality** — how the company earns money, its moat, margin trend
   and capital intensity. Use ROIC only when a sourced value exists.
2. **Earnings quality** — cash conversion, accruals, GAAP vs non-GAAP, one-off
   items and working-capital direction.
3. **Balance sheet** — net debt/EBITDA, interest coverage, current ratio,
   maturity wall and refinancing access.
4. **Dividend safety** — coverage, FCF payout, growth, dividend history and
   legal/economic rights from the worksheet.
5. **Valuation** — earnings yield, FCF yield, P/B, DCF/analyst target where
   sourced; state assumptions and margin of safety.
6. **Expectations** — consensus vs the analyst's variant perception, with at
   least three evidence lines.
7. **Base rate** — historical analogs and the measured forward-return sample,
   with sample size and caveats.
8. **Catalysts and kill switch** — what changes the view, when, and what
   invalidates the thesis.

Label each item observed, derived, inferred or unavailable. Do not record a
call while a required item is missing.

## Risk management

Decompose risk into business, valuation, balance-sheet, macro, regulatory and
liquidity risk, then add concentration and correlation at portfolio level.

For the model portfolio, report:

- gross and net exposure;
- historical VaR/CVaR and component VaR;
- stress-window returns;
- the correlation matrix;
- every limit breach.

Position sizing follows the risk score and the loss the thesis can tolerate.
No position is sized from conviction alone.

The model portfolio is a research backtest, not a live book. It excludes
borrow, financing, slippage, taxes and execution. Its selection is
point-in-time, but it is still exposed to survivorship bias in the current
security master.

## Required framing

Every view states:

- the as-of date, universe and data source;
- the simulation/label caveats;
- thesis: at most three sentences;
- recommendation: Buy / Add / Hold / Trim / Sell, or "no call";
- variant perception: consensus vs the analyst's view;
- risk summary and position-sizing implication;
- scenario table with probabilities summing to 100;
- confidence: High / Medium / Low with data-quality, forecast, sensitivity and
  conviction reasons;
- sources and open questions.

Low confidence requires a written note. A recommendation without risk
decomposition, sizing and a kill switch is not complete.
