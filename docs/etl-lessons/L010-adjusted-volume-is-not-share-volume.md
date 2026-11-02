# L010 Stored volume is back-adjusted for splits; judge liquidity in dollars

- **Status:** monitored
- **Area:** price cleaning and liquidity rules
- **Symptom:** A "thin and jumpy" rule flagged CMCT as trading a median 11 shares a day. FMP's raw volume showed it traded about 28 million shares and roughly $6M a day in December 2024.
- **Root cause:** The provider back-adjusts both price and volume for later reverse splits. Stored volume is raw volume divided by the cumulative split factor (CMCT: exactly 1/2,500), so share volume shrinks for every heavily reverse-split name. Stored close times stored volume is invariant and equals the true dollar volume.
- **Detection:** Comparing stored values with FMP's non-split-adjusted endpoint for the same dates: price ratio a constant factor, volume ratio exactly the inverse.
- **Guard:** `tests/test_backtest.py`
- **Recurrence check:** Before any price, volume or liquidity rule, compare stored values with FMP's non-split-adjusted endpoint for two or three names with recorded reverse splits. Express liquidity as close times volume. Reconstruct the traded price as stored close divided by the product of later split ratios.
