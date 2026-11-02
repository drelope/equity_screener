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
