import numpy as np
import pandas as pd

from scripts.liquidity_floor_study import VARIANTS, passes, split_factor, trailing_metrics


def test_split_factor_is_the_product_of_later_ratios_only():
    ev = pd.DataFrame({"effective_date": ["2025-01-06", "2026-03-26"], "ratio": [10.0, 10.0]})

    got = split_factor(pd.DatetimeIndex(["2024-12-31", "2025-06-01", "2026-04-01"]), ev)

    assert got.tolist() == [100.0, 10.0, 1.0]


def test_the_floors_keep_only_names_that_clear_every_threshold():
    u = pd.DataFrame({"security_id": ["a", "b", "c"]})
    price = pd.Series({"a": 1.0, "b": 6.0, "c": 9.0})
    dollar = pd.Series({"a": 9e6, "b": 2e5, "c": 3e6})

    assert passes(u, price, dollar, 5.0, 1e6)["security_id"].tolist() == ["c"]
    assert passes(u, price, dollar)["security_id"].tolist() == ["a", "b", "c"]


def test_a_name_with_no_trailing_data_fails_a_floor():
    u = pd.DataFrame({"security_id": ["ghost"]})

    assert passes(u, pd.Series(dtype=float), pd.Series(dtype=float), 2.0).empty


def test_traded_price_divides_out_later_splits_and_dollar_volume_needs_no_adjustment():
    """Stored close and volume are both back-adjusted by the same factor, so their product is
    the true dollar volume, and close / factor is the price actually paid."""
    days = pd.bdate_range("2024-12-02", periods=70)
    close = pd.DataFrame({"S": np.full(70, 2500.0)}, index=days)
    volume = pd.DataFrame({"S": np.full(70, 400.0)}, index=days)  # 1,000,000 raw shares / 2,500
    events = {"S": pd.DataFrame({"effective_date": ["2030-01-01"], "ratio": [2500.0]})}

    price, dollar = trailing_metrics(close, volume, events, days[-1])

    assert price["S"] == 1.0  # $1 a share as traded
    assert dollar["S"] == 1_000_000.0  # $1M a day


def test_every_variant_is_named_and_the_baseline_is_unfiltered():
    assert VARIANTS["baseline"] == {}
    assert set(VARIANTS["long_only"]) == {"short_gross"}


def test_cost_rises_as_liquidity_falls_and_unknown_liquidity_is_the_most_expensive():
    from scripts.liquidity_floor_study import cost_bps

    assert cost_bps(50_000_000) < cost_bps(5_000_000) < cost_bps(500_000) < cost_bps(100_000)
    assert cost_bps(10) == cost_bps(float("nan")) == cost_bps(None) == 250.0


def test_period_cost_charges_only_the_traded_notional_plus_the_short_borrow():
    from scripts.liquidity_floor_study import period_costs

    d1, d2 = pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")
    books = {
        d1: pd.Series({"a": 0.5, "s": -0.25}),
        d2: pd.Series({"a": 0.5, "s": -0.25}),  # unchanged: nothing traded the second month
    }
    dollar = {d1: pd.Series({"a": 20e6, "s": 20e6}), d2: pd.Series({"a": 20e6, "s": 20e6})}

    cost = period_costs(books, dollar, [d1, d2], 1.0)

    first = (0.5 * 5 + 0.25 * 5) / 1e4 + 0.25 * 100 / 1e4 / 12
    assert abs(cost[d1] - first) < 1e-12
    assert abs(cost[d2] - 0.25 * 100 / 1e4 / 12) < 1e-12  # borrow only


def test_a_cash_period_resets_the_book_so_the_next_one_pays_full_entry_cost():
    from scripts.liquidity_floor_study import period_costs

    d1, d2, d3 = (pd.Timestamp(x) for x in ("2024-01-31", "2024-02-29", "2024-03-29"))
    books = {d1: pd.Series({"a": 1.0}), d3: pd.Series({"a": 1.0})}
    dollar = {d: pd.Series({"a": 20e6}) for d in (d1, d3)}

    cost = period_costs(books, dollar, [d1, d2, d3], 1.0)

    assert cost[d2] == 0.0 and abs(cost[d3] - cost[d1]) < 1e-12


def test_net_metrics_subtract_costs_and_the_multiplier_scales_them():
    from scripts.liquidity_floor_study import net_metrics, period_costs

    idx = pd.date_range("2024-01-31", periods=12, freq="ME")
    gross = pd.Series(0.02, index=idx)
    books = {d: pd.Series({"a": 1.0}) for d in idx}
    dollar = {d: pd.Series({"a": 20e6}) for d in idx}

    free = net_metrics(gross, period_costs(books, dollar, list(idx), 0.0), 0.0)
    paid = net_metrics(gross, period_costs(books, dollar, list(idx), 2.0), 0.0)

    assert paid["annual_return"] < free["annual_return"]
    assert paid["cost_drag_per_year"] > 0 == free["cost_drag_per_year"]
