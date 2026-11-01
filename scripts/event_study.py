"""Event study of ex-dividend dates and monthly options expiration.

Read-only against the warehouse. Prints the results and writes them to
``artifacts/event_study/`` (gitignored). Methodology and its limits are in
``src/crispdm/event_study.py``.

    python -m scripts.event_study
    python -m scripts.event_study --from 2019-01-02 --top-liquid 1000
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.crispdm import event_study as es
from src.crispdm.db import read_df

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "event_study"

PRICES_SQL = """
SELECT m.security_id::text AS security_id, m.observation_date, m.close::float8 AS close,
       m.volume::float8 AS volume
FROM raw.market_data m
JOIN reference.securities s USING (security_id)
WHERE s.security_type = 'common_stock' AND m.close > 0 AND m.observation_date >= :start
"""

# FMP/OpenBB rows carry the true ex-date. SEC_XBRL rows use the period end as a proxy
# and would put the event on the wrong day, so they are excluded.
EVENTS_SQL = """
SELECT d.security_id::text AS security_id, d.ex_dividend_date AS ex_date,
       COALESCE(d.adjusted_amount, d.amount)::float8 AS amount
FROM raw.dividend_data d
JOIN reference.securities s USING (security_id)
WHERE d.provider = 'OPENBB' AND d.amount > 0 AND s.security_type = 'common_stock'
  AND d.ex_dividend_date >= :start
"""


def _fmt(stat: es.OffsetStat, critical: float) -> str:
    t = "  n/a" if stat.t is None else f"{stat.t:+5.2f}"
    flag = "" if stat.t is None or abs(stat.t) < critical else "  <-- beyond Bonferroni"
    return f"  {stat.offset:+3d}  n={stat.n:<5d} mean={stat.mean * 1e4:+7.2f} bp  t={t}{flag}"


def run(start: str, top_liquid: int) -> dict:
    prices = read_df(PRICES_SQL, {"start": start})
    prices["observation_date"] = pd.to_datetime(prices["observation_date"])
    close = prices.pivot(
        index="observation_date", columns="security_id", values="close"
    ).sort_index()
    volume = prices.pivot(
        index="observation_date", columns="security_id", values="volume"
    ).sort_index()
    del prices
    returns = es.daily_returns(close)
    market = es.market_return(returns)
    liquid = es.liquid_mask(close, volume, top=top_liquid)
    market_liquid = es.market_return(returns, liquid)
    opex = es.third_fridays(close.index)
    print(
        f"{close.shape[1]} securities, {len(close)} trading days, {len(opex)} opex dates",
        flush=True,
    )

    result: dict = {
        "universe": {"securities": close.shape[1], "days": len(close), "opex_dates": len(opex)}
    }
    critical = es.bonferroni_t(len(range(*es.OPEX_WINDOW)) + 1)
    print(
        f"\n=== Monthly opex: market return by trading-day offset (Bonferroni |t| > {critical:.2f}) ==="
    )
    for label, series in (
        ("all stocks >= $5", market),
        (f"top {top_liquid} by dollar volume", market_liquid),
    ):
        stats = es.opex_study(series, opex)
        disp = es.opex_dispersion(series, opex)
        print(f"\n{label}")
        for s in stats:
            print(_fmt(s, critical))
        if disp:
            print(
                f"  |return| on opex {disp['opex_mean_abs'] * 1e4:.1f} bp vs other days "
                f"{disp['other_mean_abs'] * 1e4:.1f} bp (t={disp['t']:+.2f})"
            )
        result[f"opex[{label}]"] = {"offsets": [asdict(s) for s in stats], "dispersion": disp}

    events = read_df(EVENTS_SQL, {"start": start})
    events["ex_date"] = pd.to_datetime(events["ex_date"])
    payers = es.payer_mask(close.index, close.columns, events)
    market_payers = es.market_return(returns, payers)
    print(f"payer benchmark: mean {payers.sum(axis=1).mean():.0f} securities per day")
    ex = es.ex_dividend_events(close, returns, market_payers, events)
    critical_ex = es.bonferroni_t(len(range(*es.EX_WINDOW)) + 1)
    groups = {"all events": ex}
    if len(ex) > 300:
        groups["top-tercile yield"] = ex[ex["yield"] >= ex["yield"].quantile(2 / 3)]
        groups["bottom-tercile yield"] = ex[ex["yield"] <= ex["yield"].quantile(1 / 3)]
        half = ex["ex_date"].median()
        groups["first half of sample"] = ex[ex["ex_date"] <= half]
        groups["second half of sample"] = ex[ex["ex_date"] > half]
    if len(ex) > 300 and opex:
        # Early exercise of calls ahead of an ex-date ties options to ex-dates, so check
        # whether ex-dates that land close to monthly expiration behave differently.
        opex_pos = close.index.get_indexer(opex)
        ex_pos = close.index.get_indexer(ex["ex_date"])
        distance = abs(ex_pos[:, None] - opex_pos[None, :]).min(axis=1)
        groups["ex-date within 2 days of opex"] = ex[distance <= 2]
        groups["ex-date more than 2 days from opex"] = ex[distance > 2]
    print(
        f"\n=== Ex-dividend abnormal return (adjusted to the dividend-payer market, yield <= 10%, winsorized 1%; Bonferroni |t| > {critical_ex:.2f}) ==="
    )
    print(f"{len(events)} dividends loaded, {len(ex)} usable events")
    for label, frame in groups.items():
        study = es.ex_dividend_study(frame)
        if not study["n"]:
            continue
        dr = study["drop_ratio"]
        print(
            f"\n{label}: {study['n']} events on {study['dates']} ex-dates; "
            f"price drop / dividend: median {dr['median']:.2f}, trimmed mean {dr['trimmed_mean']:.2f}"
        )
        for s in study["offsets"]:
            print(_fmt(s, critical_ex))
        for name, c in study["cumulative"].items():
            t = "n/a" if c["t"] is None else f"{c['t']:+.2f}"
            print(f"  {name}: {c['mean'] * 1e4:+.1f} bp (t={t}, {c['dates']} dates)")
        study["offsets"] = [asdict(s) for s in study["offsets"]]
        result[f"ex_dividend[{label}]"] = study
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", default="2019-01-02")
    parser.add_argument("--top-liquid", type=int, default=1000)
    args = parser.parse_args()
    result = run(args.start, args.top_liquid)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"results_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
