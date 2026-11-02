# L011 A gross backtest overstates a strategy that trades illiquid names

- **Status:** monitored
- **Area:** backtest interpretation
- **Symptom:** The backtest's Sharpe of 1.10 looked like a recovered result after the split fix, but its edge sat in cheap, illiquid names: at a median dollar volume of $1M a day or more the Sharpe was 0.06, and about half the return came from a short sleeve of hard-to-borrow microcaps.
- **Root cause:** The backtest charges no trading cost and no borrow fee, and turnover is about 6.2x a year one way. Gross returns say nothing about what a name costs to trade or to short.
- **Detection:** A floor study (price, dollar volume, long-only) and an illustrative cost model by liquidity tier. At assumed costs the baseline falls from 1.02 to 0.77 (0.89 at half the costs, 0.51 at double); a $250k dollar-volume floor falls less (0.60, still 0.50 at double); nothing earns anything above $1M a day.
- **Guard:** `scripts/liquidity_floor_study.py`, `tests/test_liquidity_floor_study.py`
- **Recurrence check:** Before reporting a backtest result, run `python -m scripts.liquidity_floor_study --variant baseline` and one floor variant, and state the after-cost Sharpe with its 0.5x and 2x sensitivity next to the gross figure. The cost tiers are assumptions, not measurements.
