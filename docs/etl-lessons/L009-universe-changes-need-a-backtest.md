# L009 A type change moves the scored universe; measure it first

- **Status:** monitored
- **Area:** classification and portfolio selection
- **Symptom:** Retyping 304 warrants, notes and units out of common_stock removed 92 securities from the latest scored universe.
- **Root cause:** Portfolio selection filters on security_type = 'common_stock'.
- **Detection:** A before and after backtest on the same code and months: Sharpe 0.863 to 0.828, within noise for 93 periods. Retyping 363 real common stocks into the universe then dropped Sharpe to 0.695: names that could never be selected became selectable, and their price histories were unadjusted for reverse splits (CMCT 1-for-10 on 2025-01-06, no event on record), turning one short into a -50% month. Loading their splits lifted Sharpe to 1.159. Any change that widens the universe must also load split history for the newly eligible names.
- **Guard:** `scripts/backtest.py`
- **Recurrence check:** Run `python -m scripts.backtest` before and after any change that moves securities across the common_stock boundary, and report both.
  Floors measured afterwards (scripts/liquidity_floor_study.py, same months, no costs): the book's edge sits in cheap and illiquid names. Sharpe 1.10 unfiltered, 0.74 with median dollar volume of at least 250k, 0.06 at 1M, 0.37 with a price of at least 5, 0.54 long-only. The headline return is not investable.
