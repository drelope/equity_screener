# L009 A type change moves the scored universe; measure it first

- **Status:** monitored
- **Area:** classification and portfolio selection
- **Symptom:** Retyping 304 warrants, notes and units out of common_stock removed 92 securities from the latest scored universe.
- **Root cause:** Portfolio selection filters on security_type = 'common_stock'.
- **Detection:** A before and after backtest on the same code and months: Sharpe 0.863 to 0.828, within noise for 93 periods.
- **Guard:** `scripts/backtest.py`
- **Recurrence check:** Run `python -m scripts.backtest` before and after any change that moves securities across the common_stock boundary, and report both.
