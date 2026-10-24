"""Walk-forward backtest of the model portfolio over the stored month-end scores.

Read-only against the warehouse. Writes the daily series, the per-period table
and the metrics to ``artifacts/backtests/`` (gitignored) and prints the metrics.
The dashboard reads the newest complete run from that directory.

    python -m scripts.backtest
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.crispdm.backtest import run_from_warehouse

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "backtests"


def main() -> int:
    result = run_from_warehouse()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    daily_path = OUTPUT_DIR / f"daily_{stamp}.csv"
    periods_path = OUTPUT_DIR / f"periods_{stamp}.csv"
    metrics_path = OUTPUT_DIR / f"metrics_{stamp}.json"
    result.daily.to_csv(daily_path)
    result.periods.to_csv(periods_path, index=False)
    metrics_path.write_text(json.dumps(result.metrics, indent=2, sort_keys=True), encoding="utf-8")

    print(
        f"periods: {len(result.periods)} (held {result.metrics['held_periods']}, "
        f"cash {result.metrics['cash_periods']})"
    )
    print(f"daily observations: {len(result.daily)}")
    for key in sorted(result.metrics):
        value = result.metrics[key]
        text = f"{value:.4f}" if isinstance(value, float) else str(value)
        print(f"  {key}: {text}")
    print(f"wrote {daily_path.name}, {periods_path.name} and {metrics_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
