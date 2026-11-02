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
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.crispdm import backtest as bt
from src.crispdm import portfolio as pf
from src.crispdm.db import read_df

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "liquidity_floor_study"
WINDOW = 60
#: Illustrative one-way trading cost in basis points by trailing median dollar volume, as
#: (minimum dollar volume, bps). These are assumptions, not measurements: half the spread plus
#: impact for a small order, rising steeply as liquidity falls. Scaled by COST_MULTIPLIERS.
COST_TIERS_BPS = (
    (10_000_000.0, 5.0),
    (1_000_000.0, 15.0),
    (250_000.0, 40.0),
    (50_000.0, 100.0),
    (0.0, 250.0),
)
#: Annual borrow fee on short notional (an easy-to-borrow rate; hard-to-borrow names cost far more).
SHORT_BORROW_BPS_PER_YEAR = 100.0
COST_MULTIPLIERS = (0.0, 0.5, 1.0, 2.0)
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


def cost_bps(dollar_volume: float) -> float:
    """One-way cost in bps for a name with this trailing median dollar volume."""
    value = 0.0 if dollar_volume is None or np.isnan(dollar_volume) else float(dollar_volume)
    for floor, bps in COST_TIERS_BPS:
        if value >= floor:
            return bps
    return COST_TIERS_BPS[-1][1]


def period_costs(books: dict, dollar_by_date: dict, formations, multiplier: float) -> pd.Series:
    """Cost of each period as a fraction of NAV: traded notional per name times its bps,
    plus the borrow fee on short notional for one month."""
    previous = pd.Series(dtype=float)
    out = {}
    for day in formations:
        weights = books.get(day)
        if weights is None:
            out[day] = 0.0
            previous = pd.Series(dtype=float)
            continue
        traded = weights.sub(previous, fill_value=0.0).abs()
        dollar = dollar_by_date.get(day, pd.Series(dtype=float))
        bps = pd.Series({sid: cost_bps(dollar.get(sid)) for sid in traded.index})
        trading = float((traded * bps).sum()) / 1e4
        borrow = float(weights[weights < 0].abs().sum()) * SHORT_BORROW_BPS_PER_YEAR / 1e4 / 12
        out[day] = multiplier * (trading + borrow)
        previous = weights
    return pd.Series(out)


def net_metrics(gross: pd.Series, costs: pd.Series, rf_monthly: float) -> dict:
    """Annualised return, volatility and Sharpe from monthly returns after costs."""
    net = gross - costs.reindex(gross.index).fillna(0.0)
    years = len(net) / 12.0
    growth = float((1.0 + net).prod())
    excess = net - rf_monthly
    vol = float(net.std() * np.sqrt(12))
    return {
        "annual_return": growth ** (1.0 / years) - 1.0 if growth > 0 else -1.0,
        "annual_volatility": vol,
        "sharpe": float(excess.mean() / net.std() * np.sqrt(12)) if net.std() > 0 else float("nan"),
        "cost_drag_per_year": float(costs.reindex(gross.index).fillna(0.0).sum() / years),
    }


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
    books: dict = {}
    dollar_by_date: dict = {}
    state = {"day": None}

    def universe_for(day):
        universe = original(day)
        state["day"] = pd.Timestamp(day)
        _, dollar = trailing_metrics(close, volume, events, pd.Timestamp(day))
        dollar_by_date[pd.Timestamp(day)] = dollar
        if "min_price" in cfg or "min_dollar_volume" in cfg:
            price, dollar = trailing_metrics(close, volume, events, pd.Timestamp(day))
            universe = passes(
                universe, price, dollar, cfg.get("min_price"), cfg.get("min_dollar_volume")
            )
        return universe

    select = pf.select_portfolio

    def recording_select(*args, **kwargs):
        if "short_gross" in cfg:
            kwargs.setdefault("short_gross", cfg["short_gross"])
        book = select(*args, **kwargs)
        books[state["day"]] = book.set_index(book["security_id"].astype(str))["weight"].astype(
            float
        )
        return book

    pf.select_portfolio = recording_select
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
    periods.index = pd.to_datetime(periods.index)
    rf = read_df(
        "SELECT avg(value)::float8 AS v FROM raw.macro_series WHERE series_id = :s",
        {"s": pf.RISK_FREE_SERIES},
    ).v[0]
    rf_monthly = float(rf) / 100.0 / 12.0
    after_costs = {
        f"x{m:g}": net_metrics(
            periods, period_costs(books, dollar_by_date, list(periods.index), m), rf_monthly
        )
        for m in COST_MULTIPLIERS
    }
    metrics = dict(result.metrics)
    metrics["after_costs"] = after_costs
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
