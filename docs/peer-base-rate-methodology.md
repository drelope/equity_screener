# Peer base rate methodology

Step 15 of the investment-analysis workflow — "Historical analogs" — reports a base
rate: the share of comparable historical setups that produced a positive forward
twelve-month total return. This note explains what that number is measured from, why it
is sampled the way it is, and what it does not support. The worksheet field contract is
in [InvestmentAnalysisWorkflow.md](InvestmentAnalysisWorkflow.md); this is the reasoning
behind it.

## Why the security's own history is not a base rate

The step originally reported the security's own three trailing twelve-month windows.
That answers "how has this one security gone", which is mostly its own past: three
overlapping windows of one name are not a sample of anything, and a "70%" computed from
three data points reads with the same authority as a rate over two hundred. Step 15
asks a different question — "what happened to setups like this one" — and that question
needs comparable securities, not the same one three times over.

## The forward-return table

`model.forward_returns` stores, for every security and every setup date, the total
return over the following 252 trading days.

| Column | Meaning |
|---|---|
| `security_id`, `as_of_date` | the setup; primary key |
| `forward_date` | the actual date the window ends, trading-day based |
| `window_days` | returns consumed, so a short window is visible rather than implied |
| `total_return` | price plus dividends, compounded |
| `price_return`, `dividend_return` | the same window split into its two sources |

Only complete windows are stored. The build materialises `2019-01-02 .. 2025-10-20`;
the most recent twelve months of setups have no forward window yet, so they are absent
rather than short. That lag is a property of the measurement, not a gap to be
backfilled.

## The canonical total return

The rules mirror `src/crispdm/features.py`, so the trailing and forward definitions
cannot drift apart.

1. **OPENBB dividends only.** `raw.dividend_data` holds two providers with incompatible
   bases. `OPENBB` stores per-payment rows with real ex-dates (KO 2023: four payments of
   0.46). `SEC_XBRL` stores **cumulative year-to-date** per-share amounts at fiscal
   period ends (KO 2023: 0.46, 0.92, 1.38, 1.84 at the four quarter-ends). Summing the
   SEC rows books 4.60 for a year that paid 1.84, and summing both providers books 6.44.
   2,561 securities have rows from both, so the choice is not academic.
2. **A payment is booked to the first price row on or after its ex-date.** An ex-date
   can fall on a day with no price row (a market holiday), and an equality join would
   silently drop the payment rather than move it.
3. **A single payment larger than the prior close is a unit or currency error**, not a
   dividend, and is left out of the return rather than discarding the whole security
   (`MAX_SINGLE_PAYMENT_RATIO = 1.0`). The stored series contains payments on the order
   of hundreds of trillions per share (TOPS, 2006); one such row would turn a twelve-month
   return into a number no holder ever earned. Genuine special dividends of 30-50% of
   price are kept.
4. **The window must be complete.** A window function over "the next 252 rows" returns a
   *partial* sum when fewer than 252 rows follow, so a 29-day stretch can be reported as
   a twelve-month return. The build keeps a window only when it counts exactly 252
   returns.

`raw.market_data.adjusted_close` is 100% NULL — the only provider (OPENBB) never
supplies it — so price plus dividend is the only route to a total return. Dividends are
treated as reinvested at the close of their ex-date.

## Why the sample is monthly, not daily

The table is daily, because a forward return can be measured from any setup date. The
**base-rate query** does not use every row. A forward twelve-month return is almost
perfectly serially correlated with the one a day earlier: the two windows share 251 of
their 252 days. Measured lag-1 autocorrelation on JNJ's stored windows is **0.994**.

Sampling every day would therefore report roughly ten times more "observations" than
are independent, and a rate whose apparent confidence is an artefact of overlap. Taking
the first observation date of each calendar month leaves windows 21-25 trading days
apart, which is the finest defensible non-overlapping grid at this horizon.

## Building the peer sample

- **Peers are the target's industry**, from `clean.ticker_profile.industry`.
- **Conditions are point-in-time.** Each peer observation is scored on
  `model.features.dividend_yield` and `dividend_coverage` as they stood at that
  observation's own `as_of_date`, not today. A 2019 peer is matched on what was true in
  2019.
- **Price quality is filtered first**: `price_quality = 'ok'` and `current_price >= 5`
  (`MIN_PRICE`). Split-artifact and sub-penny prices make yield and coverage
  meaningless. Across the whole monthly sample they are 70,505 of 394,377
  observations, and including them lifts the mean forward return from +7.6% to
  +184.8%, with a maximum of +51,499% — returns no holder ever earned. Within one
  industry the filter can be close to a no-op (1,693 to 1,680 here), but it is
  applied everywhere so a single bad price cannot leak into a yield comparison.
- **Similarity is relative, not absolute**: both yield and coverage within
  `SIMILARITY_BAND = 0.5` (±50%) of the target's current values. At twice the yield a
  peer is a different setup, and the band has to be wide enough to leave a usable sample
  and narrow enough to mean something.
- **The headline needs `MIN_OBSERVATIONS = 30`.** Below that the rate is one or two data
  points wearing a percentage. Where the similar slice is thin, the worksheet falls back
  to the security's own stored windows and says so in the confidence note.

The rate is computed over the **similar slice**; the wider peer group is carried
alongside as context, so a reader can see whether the sector was generally kind over the
period and whether the closest setups were.

## Measured result

JNJ at 2026-10-20, monthly snapshots, quality-filtered:

| Slice | Obs | Positive | Average | Median | p05-p95 |
|---|---|---|---|---|---|
| Drug Manufacturers - General | 1,680 | 64.52% | +9.04% | +8.88% | — |
| Similar (yield and coverage within ±50%) | 211 | 70.14% | +14.22% | +8.88% | -13.7% to +66.5% |

The similar slice is meaningfully better than the broad peer slice (70.1% vs 64.5%),
which is what a narrowing base rate should do.

## Limits disclosed with every rate

These are properties of the data, and the worksheet shows them beside the number.

- **Industry look-ahead.** `clean.ticker_profile.industry` is a current snapshot; the
  warehouse has no industry vintages. Using it to define peers for 2019 rows is mild
  look-ahead.
- **Descriptive, not predictive.** The sample is drawn from the same period the rate
  describes. It frames a position probabilistically; it is not a validated forecast.
- **The 252-day lag.** The most recent year of setups is not yet scoreable, so the rate
  always describes the past, never the present.

## Where this lives

| Path | Role |
|---|---|
| `src/crispdm/returns.py` | canonical forward-return SQL, payload and persistence |
| `sql/migrations/V0091_forward_returns.sql` | `model.forward_returns` |
| `scripts/build_forward_returns.py` | density-aware, idempotent materialisation |
| `src/crispdm/analogs.py` | monthly peer sample, similarity, statistics, caveats |
| `app/analysis_autofill.py` | step-15 wiring and own-history fallback |
| `src/crispdm/features.py` | the trailing total-return definition this mirrors |
| `scripts/run_full_etl.py` | stage 7b, refreshed with the features |
| `src/crispdm/ops/catalog.py` | the `build_forward_returns` operational task |
