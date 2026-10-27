# Reports and Dashboard

Load when: preparing a morning note, performance/risk report, IC memo or
research note, or checking one of the seven dashboard tabs.

## Report contract

Every report states the as-of date, universe, data source and
simulation/label caveats. The investment view uses:

- thesis: at most three sentences;
- recommendation: Buy / Add / Hold / Trim / Sell, or "no call";
- variant perception: consensus vs the analyst's view;
- risk summary and position sizing;
- scenario table with probabilities summing to 100;
- confidence: High / Medium / Low with data-quality, forecast, sensitivity
  and conviction reasons;
- sources and open questions.

An IC memo is generated only from a saved **Final** worksheet. A Draft may be
summarised, but it is labelled Draft and is not an investment-committee memo.
Optional local-LLM text is a draft aid; it never supplies a number and never
saves a recommendation.

## Seven dashboard tabs

1. **Portfolio Dashboard** — model NAV, return, gross/net exposure, sector
   allocation and top/bottom positions.
2. **Performance Analytics** — monthly heatmap, Sharpe/Sortino/Calmar/IR/Omega
   and drawdown.
3. **Risk Monitor** — VaR/CVaR, component VaR, stress tests, correlation
   matrix and limit dashboard.
4. **Position Book** — 23-position long/short table with P&L, VaR
   contribution, model conviction and F-Score coverage.
5. **Factor Attribution** — style-exposure radar, sector weights vs the
   equal-weight scored universe, sector contribution and style drift when at
   least two completed rebalances exist; otherwise show an explicit
   unavailable state.
6. **Research Pipeline** — kanban-style Not analysed/Draft/Final board,
   coverage tracker and ex-dividend catalyst calendar.
7. **Reports Center** — morning note, performance report, risk report, IC memo
   and research note, downloadable as Markdown.

## Labels and limits

- The model portfolio is simulated; never present it as live or investable.
- Gross exposure is not a target return and may exceed net exposure.
- Style exposures are proxies, not a Fama-French regression.
- VaR/CVaR are historical-simulation estimates; state the method and window.
- F-Score coverage is reported; missing tests are not silently passed.
- Dashboard empty states must say which input is unavailable and why.
