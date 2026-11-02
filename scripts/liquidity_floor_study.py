"""Measure how price and dollar-volume floors, and dropping the short sleeve, change the backtest.

Read-only against the warehouse; nothing it computes is used by the pipeline. Each variant
filters the scored universe at every formation date from trailing data only (no lookahead):

* traded price = stored close / product of the split ratios dated after the observation
  (the stored series is back-adjusted to today's share basis, see docs/etl-lessons/L010);
* dollar volume = stored close * stored volume (invariant to the adjustment), median of the
  last ``WINDOW`` sessions.

    python -m scripts.liquidity_floor_study --variant baseline
    python -m scripts.liquidity_floor_study --list
"""

from __future__ import annotations

import argparse
import functools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.crispdm import backtest as bt
from src.crispdm import portfolio as pf
from src.crispdm.db import read_df

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "liquidity_floor_study"
WINDOW = 60
VARIANTS = {
    "baseline": {},
    "price_ge_2": {"min_price": 2.0},
    "price_ge_5": {"min_price": 5.0},
    "dollar_vol_ge_250k": {"min_dollar_volume": 250_000.0},
    "dollar_vol_ge_1m": {"min_dollar_volume": 1_000_000.0},
    "price5_and_dv1m": {"min_price": 5.0, "min_dollar_volume": 1_000_000.0},
    "long_only": {"short_gross": 0.0},
}


def split_factor(dates: pd.DatetimeIndex, events: pd.DataFrame) -> np.ndarray:
    """Product of split ratios dated after each date (1.0 when none)."""
    factor = np.ones(len(dates))
    for event_date, ratio in zip(events["effective_date"], events["ratio"]):
        factor = np.where(dates < pd.Timestamp(event_date), factor * float(ratio), factor)
    return factor


def trailing_metrics(close: pd.DataFrame, volume: pd.DataFrame, events: dict, day, window=WINDOW):
    """Traded price on ``day`` and median trailing dollar volume, per security."""
    history = close.loc[:day].tail(window)
    if history.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    dollar = (history * volume.loc[history.index]).median(axis=0, skipna=True)
    last = history.iloc[-1]
    price = pd.Series(
        {
            sid: value / (split_factor(pd.DatetimeIndex([history.index[-1]]), events[sid])[0])
            if sid in events
            else value
            for sid, value in last.items()
        }
    )
    return price, dollar


def passes(universe: pd.DataFrame, price, dollar, min_price=None, min_dollar_volume=None):
    ids = universe["security_id"].astype(str)
    keep = pd.Series(True, index=universe.index)
    if min_price is not None:
        keep &= ids.map(price).fillna(0.0) >= min_price
    if min_dollar_volume is not None:
        keep &= ids.map(dollar).fillna(0.0) >= min_dollar_volume
    return universe[keep].reset_index(drop=True)


def run(variant: str) -> dict:
    cfg = VARIANTS[variant]
    ids = read_df(
        "SELECT security_id::text AS s FROM reference.securities "
        "WHERE security_type = 'common_stock'"
    ).s.tolist()
    prices = pf.load_prices(ids, "2018-06-01", "2026-10-30")
    close = prices.pivot(index="observation_date", columns="security_id", values="close")
    volume = prices.pivot(index="observation_date", columns="security_id", values="volume")
    del prices
    ev = read_df(
        "SELECT security_id::text AS sid, effective_date, ratio::float8 AS ratio "
        "FROM raw.corporate_actions WHERE action_type = 'split' AND ratio > 0"
    )
    events = {sid: g for sid, g in ev.groupby("sid")}
    original = pf.load_universe

    def universe_for(day):
        universe = original(day)
        if "min_price" in cfg or "min_dollar_volume" in cfg:
            price, dollar = trailing_metrics(close, volume, events, pd.Timestamp(day))
            universe = passes(
                universe, price, dollar, cfg.get("min_price"), cfg.get("min_dollar_volume")
            )
        return universe

    select = pf.select_portfolio
    if "short_gross" in cfg:
        pf.select_portfolio = functools.partial(select, short_gross=cfg["short_gross"])
    try:
        schedule = bt.rebalance_schedule(pf.load_score_dates())
        result = bt.run_walk_forward(
            schedule,
            universe_for=universe_for,
            prices_for=lambda i, a, b: pf.load_prices(i, a, b),
            risk_free_for=lambda index: pf.load_risk_free(index),
            split_events=pf.load_split_events(),
        )
    finally:
        pf.select_portfolio = select
    periods = result.periods.set_index("formation").period_return
    metrics = dict(result.metrics)
    metrics.update(
        variant=variant,
        monthly_std=float(periods.std()),
        worst_month=float(periods.min()),
        best_month=float(periods.max()),
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list or not args.variant:
        print("\n".join(VARIANTS))
        return 0
    metrics = run(args.variant)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.variant}.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(
        args.variant,
        {
            k: round(metrics[k], 4)
            for k in ("sharpe", "annual_return", "annual_volatility", "max_drawdown")
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
