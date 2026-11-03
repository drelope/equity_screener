"""Selection, return, risk and attribution rules for the model portfolio."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.crispdm.portfolio import (
    BASE_NAV,
    MIN_PRICE,
    clean_prices,
    exclude_unreliable,
    factor_exposures,
    holdings_table,
    load_risk_free,
    load_universe,
    monthly_return_table,
    performance_metrics,
    piotroski_f_score,
    portfolio_returns,
    rebalance_date,
    risk_metrics,
    sector_attribution,
    select_portfolio,
    stress_scenarios,
    total_return_matrix,
)


def _universe(size=30):
    scores = np.linspace(0.99, 0.01, size)
    return pd.DataFrame(
        {
            "security_id": [f"s{index:02d}" for index in range(size)],
            "ticker": [f"T{index:02d}" for index in range(size)],
            "sector": ["Technology"] * size,
            "composite_score": scores,
            "score_coverage": 1.0,
            "dividend_income_score": scores,
            "sustainability_score": scores,
            "appreciation_score": scores,
            "risk_score": scores,
            "valuation_score": scores,
        }
    )


def test_rebalance_date_uses_the_last_date_of_a_completed_month():
    dates = pd.to_datetime(["2026-09-25", "2026-09-30", "2026-10-01", "2026-10-22"])

    assert rebalance_date(dates, as_of="2026-10-24") == pd.Timestamp("2026-09-30")
    assert rebalance_date(dates, as_of="2026-11-01") == pd.Timestamp("2026-10-22")


def test_rebalance_date_falls_back_to_the_first_date_when_no_month_is_complete():
    dates = pd.to_datetime(["2026-09-25", "2026-09-30"])

    assert rebalance_date(dates, as_of="2026-09-30") == pd.Timestamp("2026-09-25")


def test_select_portfolio_builds_equal_weight_sleeves_without_overlap():
    book = select_portfolio(_universe())

    assert len(book) == 23
    assert (book["side"] == "Long").sum() == 15
    assert (book["side"] == "Short").sum() == 8
    assert book.loc[book["side"] == "Long", "weight"].sum() == pytest.approx(1.0)
    assert book.loc[book["side"] == "Short", "weight"].sum() == pytest.approx(-0.5)
    assert book["weight"].abs().sum() == pytest.approx(1.5)
    assert book.loc[book["side"] == "Long", "weight"].nunique() == 1
    assert book.loc[book["side"] == "Short", "weight"].nunique() == 1
    assert set(book.loc[book["side"] == "Long", "ticker"]) == {
        f"T{index:02d}" for index in range(15)
    }
    assert set(book.loc[book["side"] == "Short", "ticker"]) == {
        f"T{index:02d}" for index in range(22, 30)
    }


def test_select_portfolio_can_weight_sleeves_by_inverse_volatility_when_requested():
    book = select_portfolio(_universe(), risk_parity=True)
    longs = book[book["side"] == "Long"]
    shorts = book[book["side"] == "Short"]

    assert longs["weight"].sum() == pytest.approx(1.0)
    assert shorts["weight"].sum() == pytest.approx(-0.5)
    assert book["weight"].abs().sum() == pytest.approx(1.5)
    assert (longs["weight"] > 0).all()
    assert (shorts["weight"] < 0).all()
    assert longs["weight"].nunique() > 1
    assert shorts["weight"].nunique() > 1


def test_select_portfolio_refuses_a_universe_that_cannot_fill_both_sleeves():
    with pytest.raises(ValueError, match="need 23"):
        select_portfolio(_universe(10))


def test_total_return_matrix_credits_the_dividend_on_its_price_date():
    prices = pd.DataFrame(
        {
            "security_id": ["s1", "s1", "s1"],
            "observation_date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
            "close": [100.0, 110.0, 99.0],
            "dividend": [0.0, 0.0, 11.0],
        }
    )

    returns = total_return_matrix(prices)

    assert returns.loc[pd.Timestamp("2026-01-05"), "s1"] == pytest.approx(0.10)
    assert returns.loc[pd.Timestamp("2026-01-06"), "s1"] == pytest.approx(0.0)


def test_total_return_matrix_drops_an_impossible_dividend():
    prices = pd.DataFrame(
        {
            "security_id": ["s1", "s1"],
            "observation_date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
            "close": [100.0, 110.0],
            "dividend": [0.0, 200.0],
        }
    )

    returns = total_return_matrix(prices)

    assert returns.loc[pd.Timestamp("2026-01-05"), "s1"] == pytest.approx(0.10)


def test_portfolio_returns_apply_the_short_weight_to_the_stock_return():
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    returns = pd.DataFrame({"s1": [0.01, 0.02], "s2": [0.03, 0.04]}, index=index)
    book = pd.DataFrame({"security_id": ["s1", "s2"], "weight": [1.0, -0.5]})

    path = portfolio_returns(returns, book)

    assert path["return"].to_list() == pytest.approx([-0.005, 0.0])
    assert path["nav"].iloc[-1] == pytest.approx(BASE_NAV * 0.995)


def test_performance_metrics_report_drawdown_and_hit_rate():
    returns = pd.Series(
        [0.01, -0.02, 0.03],
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )
    metrics = performance_metrics(returns)

    assert metrics["cumulative_return"] == pytest.approx(1.01 * 0.98 * 1.03 - 1.0)
    assert metrics["max_drawdown"] < 0
    assert metrics["hit_rate"] == pytest.approx(2 / 3)
    assert metrics["observations"] == 3


def test_sortino_uses_downside_deviation_over_all_observations():
    returns = pd.Series([0.02, -0.01, 0.03, -0.02, 0.01, 0.00])
    metrics = performance_metrics(returns)

    # Standard definition: DD = sqrt(mean(min(r, 0)^2)) over all N observations.
    downside = np.sqrt(np.mean(np.minimum(returns.to_numpy(), 0.0) ** 2))
    expected = returns.mean() / downside * np.sqrt(252)
    assert metrics["sortino"] == pytest.approx(expected)


def test_sharpe_subtracts_the_daily_risk_free_rate():
    returns = pd.Series(
        [0.01, -0.005, 0.012, 0.002, -0.003, 0.008],
        index=pd.bdate_range("2026-01-02", periods=6),
    )
    rate = pd.Series(0.0002, index=returns.index)

    metrics = performance_metrics(returns, risk_free=rate)

    excess = returns - rate
    assert metrics["sharpe"] == pytest.approx(excess.mean() / excess.std(ddof=1) * np.sqrt(252))
    assert metrics["risk_free_applied"] is True


def test_sharpe_falls_back_explicitly_when_the_risk_free_series_is_incomplete():
    returns = pd.Series(
        [0.01, -0.005, 0.012, 0.002],
        index=pd.bdate_range("2026-01-02", periods=4),
    )
    partial = pd.Series([0.0002, np.nan, 0.0002, 0.0002], index=returns.index)

    metrics = performance_metrics(returns, risk_free=partial)

    assert metrics["risk_free_applied"] is False
    assert metrics["sharpe"] == pytest.approx(returns.mean() / returns.std(ddof=1) * np.sqrt(252))


def test_load_risk_free_converts_the_percent_yield_to_a_compounded_daily_rate():
    dates = pd.bdate_range("2026-09-01", periods=5)
    calls = []

    def fake_query(sql, params):
        calls.append(params)
        return pd.DataFrame(
            {"observation_date": [dates[0].date()], "value": [3.6]},
        )

    rate = load_risk_free(dates, query=fake_query)

    assert calls[0]["series"] == "UST_3M"
    assert rate.index.equals(dates)
    expected = (1.036) ** (1 / 252) - 1
    assert rate.to_numpy() == pytest.approx(np.full(5, expected))


def test_load_risk_free_returns_nan_when_the_series_is_missing():
    dates = pd.bdate_range("2026-09-01", periods=3)

    rate = load_risk_free(dates, query=lambda sql, params: pd.DataFrame())

    assert rate.isna().all()


def test_sortino_is_undefined_without_any_downside():
    metrics = performance_metrics(pd.Series([0.01, 0.02, 0.03]))
    assert np.isnan(metrics["sortino"])


def test_component_var_sums_to_parametric_var():
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2026-01-02", periods=120)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(120, 3)), index=index, columns=list("abc"))
    book = pd.DataFrame({"security_id": list("abc"), "weight": [0.8, -0.3, 0.4]})

    risk = risk_metrics(returns, book)

    assert risk["components"]["component_var"].sum() == pytest.approx(risk["parametric_var"])
    assert risk["historical_var"] >= 0
    assert risk["expected_shortfall"] >= risk["historical_var"]


def test_covariance_uses_only_dates_where_every_name_has_a_return():
    from statistics import NormalDist

    rng = np.random.default_rng(11)
    index = pd.bdate_range("2026-01-02", periods=60)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(60, 3)), index=index, columns=list("abc"))
    returns.loc[index[:50], "c"] = np.nan  # name c has only ten days of history
    book = pd.DataFrame({"security_id": list("abc"), "weight": [0.5, -0.3, 0.2]})

    risk = risk_metrics(returns, book)

    complete = returns.dropna(how="any")
    weights = book.set_index("security_id")["weight"][list("abc")].to_numpy()
    expected = NormalDist().inv_cdf(0.95) * np.sqrt(weights @ complete.cov().to_numpy() @ weights)
    assert risk["covariance_observations"] == 10
    assert risk["parametric_var"] == pytest.approx(expected)
    assert risk["components"]["component_var"].sum() == pytest.approx(risk["parametric_var"])


def test_parametric_var_is_flagged_when_the_window_has_no_more_dates_than_names():
    rng = np.random.default_rng(3)
    book = pd.DataFrame({"security_id": list("abc"), "weight": [0.5, -0.3, 0.2]})

    long_window = pd.DataFrame(
        rng.normal(0, 0.01, size=(60, 3)),
        index=pd.bdate_range("2026-01-02", periods=60),
        columns=list("abc"),
    )
    short_window = long_window.iloc[:3]

    assert risk_metrics(long_window, book)["parametric_reliable"] is True
    assert risk_metrics(short_window, book)["parametric_reliable"] is False


def test_stress_scenarios_report_the_worst_observed_window():
    returns = pd.Series([0.01, -0.05, 0.02, -0.04, 0.03])

    table = stress_scenarios(returns, horizons=(1, 2))

    assert table.loc[table["horizon_days"] == 1, "worst_return"].iloc[0] == pytest.approx(-0.05)
    assert table.loc[table["horizon_days"] == 2, "worst_return"].iloc[0] == pytest.approx(
        (1 + 0.01) * (1 - 0.05) - 1
    )


def test_monthly_return_table_compounds_within_each_calendar_month():
    returns = pd.Series(
        [0.10, -0.10, 0.05],
        index=pd.DatetimeIndex(
            pd.to_datetime(["2026-01-05", "2026-01-20", "2026-02-02"]),
            name="observation_date",
        ),
        name="return",
    )

    table = monthly_return_table(returns)

    assert table.loc[table["month"] == 1, "return"].iloc[0] == pytest.approx(-0.01)
    assert table.loc[table["month"] == 2, "return"].iloc[0] == pytest.approx(0.05)


def test_piotroski_f_score_counts_all_nine_signals():
    current = pd.Series(
        {
            "net_income": 10.0,
            "assets": 100.0,
            "operating_cash_flow": 12.0,
            "debt": 20.0,
            "current_assets": 30.0,
            "current_liabilities": 20.0,
            "shares_outstanding": 100.0,
            "gross_profit": 40.0,
            "revenue": 100.0,
        }
    )
    prior = pd.Series(
        {
            "net_income": 5.0,
            "assets": 100.0,
            "operating_cash_flow": 8.0,
            "debt": 30.0,
            "current_assets": 25.0,
            "current_liabilities": 20.0,
            "shares_outstanding": 100.0,
            "gross_profit": 31.5,
            "revenue": 90.0,
        }
    )

    score, signals, complete = piotroski_f_score(current, prior)

    assert complete is True
    assert score == 9
    assert all(signals.values())


def test_piotroski_f_score_marks_missing_inputs_incomplete():
    current = pd.Series({"net_income": 10.0, "assets": None})
    prior = pd.Series({"net_income": 5.0, "assets": 100.0})

    _score, signals, complete = piotroski_f_score(current, prior)

    assert complete is False
    assert signals["positive_roa"] is None


def test_factor_exposures_are_weighted_across_each_sleeve():
    book = select_portfolio(_universe())
    exposures = factor_exposures(book)

    assert set(exposures["factor"]) == {
        "Income",
        "Sustainability",
        "Appreciation",
        "Low volatility",
        "Valuation",
    }
    assert (exposures["long"] > exposures["short"]).all()
    assert (exposures["net"] > 0).all()


def test_sector_attribution_nets_long_and_short_pnl():
    book = pd.DataFrame(
        {
            "security_id": ["s1", "s2"],
            "ticker": ["T1", "T2"],
            "sector": ["Technology", "Financials"],
            "side": ["Long", "Short"],
            "weight": [1.0, -0.5],
        }
    )
    returns = pd.DataFrame({"security_id": ["s1", "s2"], "total_return": [0.10, 0.20]})

    table = sector_attribution(book, returns)

    by_sector = table.set_index("sector")["pnl"]
    assert by_sector["Technology"] == pytest.approx(0.10 * BASE_NAV)
    assert by_sector["Financials"] == pytest.approx(-0.10 * BASE_NAV)
    assert table["pnl"].sum() == pytest.approx(0.0)


def test_holdings_table_combines_returns_f_scores_and_risk():
    book = select_portfolio(_universe(23))
    index = pd.bdate_range("2026-01-02", periods=3)
    returns = pd.DataFrame(
        {security_id: [0.0, 0.01, -0.01] for security_id in book["security_id"]},
        index=index,
    )
    f_scores = pd.DataFrame(
        {
            "security_id": book["security_id"],
            "f_score": 8,
            "f_score_max": 9,
            "f_score_complete": True,
        }
    )
    risk = risk_metrics(returns, book)

    table = holdings_table(book, returns, f_scores, risk)

    assert len(table) == 23
    assert table["pnl"].notna().all()
    assert set(table["conviction"]) <= {"High", "Medium", "Low"}
    assert table["f_score"].eq(8).all()


def test_universe_query_restricts_the_book_to_common_stock():
    captured = {}
    columns = [
        "security_id",
        "dividend_income_score",
        "sustainability_score",
        "appreciation_score",
        "risk_score",
        "valuation_score",
        "composite_score",
        "score_coverage",
    ]

    def fake_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return pd.DataFrame(columns=columns)

    load_universe(pd.Timestamp("2026-10-23"), query=fake_query)

    assert "sec.security_type = 'common_stock'" in captured["sql"]
    assert "px.close >= :min_price" in captured["sql"]
    assert captured["params"]["min_price"] == MIN_PRICE


def _series(security_id, closes, volumes=None):
    dates = pd.bdate_range("2026-09-01", periods=len(closes))
    frame = pd.DataFrame(
        {
            "security_id": security_id,
            "observation_date": dates,
            "close": closes,
            "volume": volumes if volumes is not None else [1000.0] * len(closes),
        }
    )
    return frame


def test_a_zero_volume_print_is_replaced_by_the_last_accepted_close():
    frame = _series("A", [1.0, 1.02, 1.5, 1.03], volumes=[1000, 1000, 0, 1000])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 1
    assert cleaned["close"].tolist() == pytest.approx([1.0, 1.02, 1.02, 1.03])


def test_a_spike_that_reverts_within_the_window_is_rejected():
    # The PNYG pattern: a 0.90 close, a jump to 4.99 on low volume, then a return.
    frame = _series("P", [0.90, 4.99, 0.80, 0.65], volumes=[5000, 820, 30000, 7000])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 1
    assert cleaned["close"].iloc[1] == pytest.approx(0.90)
    assert cleaned["close"].iloc[2] == pytest.approx(0.80)


def test_a_persistent_jump_is_kept_because_it_may_be_a_real_event():
    # The ADAMG pattern: the level holds after the jump, so nothing reverts.
    frame = _series("E", [8.7, 25.3, 25.2, 25.4, 25.1, 25.3, 25.2])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 0
    assert cleaned["close"].tolist() == pytest.approx(frame["close"].tolist())


def test_a_move_inside_the_spike_threshold_is_kept():
    frame = _series("N", [10.0, 14.0, 9.0, 12.0], volumes=[1000, 1000, 1000, 1000])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 0
    assert cleaned["close"].tolist() == pytest.approx([10.0, 14.0, 9.0, 12.0])


def test_an_unknown_volume_is_not_treated_as_zero():
    frame = _series("U", [1.0, 1.02, 1.05], volumes=[float("nan"), float("nan"), float("nan")])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 0
    assert cleaned["close"].tolist() == pytest.approx([1.0, 1.02, 1.05])


def test_each_security_is_cleaned_on_its_own_series():
    stale = _series("A", [1.0, 1.5], volumes=[1000, 0])
    clean = _series("B", [2.0, 2.1], volumes=[1000, 1000])

    cleaned, rejected = clean_prices(pd.concat([stale, clean], ignore_index=True))

    assert rejected == 1
    b = cleaned[cleaned["security_id"] == "B"]["close"].tolist()
    assert b == pytest.approx([2.0, 2.1])


def test_an_absurd_close_is_replaced_by_the_last_accepted_close():
    # The WHLR pattern: a close in the hundreds of billions between ordinary prints.
    frame = _series("W", [2.0, 2.1, 4.3e11, 2.05, 2.1])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 1
    assert cleaned["close"].tolist() == pytest.approx([2.0, 2.1, 2.1, 2.05, 2.1])


def test_a_sub_penny_close_inside_the_range_is_kept():
    frame = _series("S", [0.0005, 0.00052, 0.00051])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 0
    assert cleaned["close"].tolist() == pytest.approx([0.0005, 0.00052, 0.00051])


def test_a_split_the_price_shows_is_adjusted_so_the_split_day_has_no_return():
    frame = _series("SP", [100.0, 101.0, 50.5, 51.0, 51.5])
    events = pd.DataFrame(
        {
            "security_id": ["SP"],
            "date": [pd.bdate_range("2026-09-01", periods=5)[2]],
            "ratio": [0.5],
        }
    )

    cleaned, rejected = clean_prices(frame, split_events=events)

    assert cleaned.attrs["splits_adjusted"] == 1
    assert rejected == 0
    assert cleaned["close"].tolist() == pytest.approx([50.0, 50.5, 50.5, 51.0, 51.5])
    returns = cleaned["close"].pct_change().tolist()
    assert returns[1] == pytest.approx(0.01)  # the day before the split keeps its real move
    assert returns[2] == pytest.approx(0.0)  # the split day itself has no return


def test_a_reported_split_the_price_does_not_show_changes_nothing():
    frame = _series("NS", [100.0, 101.0, 101.5, 102.0])
    events = pd.DataFrame(
        {
            "security_id": ["NS"],
            "date": [pd.bdate_range("2026-09-01", periods=4)[2]],
            "ratio": [0.5],
        }
    )

    cleaned, _ = clean_prices(frame, split_events=events)

    assert cleaned.attrs["splits_adjusted"] == 0
    assert cleaned["close"].tolist() == pytest.approx([100.0, 101.0, 101.5, 102.0])


def test_split_events_are_mapped_from_ticker_to_each_identity_with_that_ticker(tmp_path):
    from src.crispdm.portfolio import load_split_events

    path = tmp_path / "fmp_splits.csv"
    path.write_text(
        "ticker,date,numerator,denominator,split_type\n"
        "WHLR,2026-09-22,1,9,stock-split\n"
        "AAPL,2020-08-31,4,1,stock-split\n"
        "ZZZ,2020-01-01,,,stock-split\n",
        encoding="utf-8",
    )

    def fake_query(sql, params):
        return pd.DataFrame(
            {"security_id": ["id-1", "id-2", "id-3"], "ticker": ["WHLR", "WHLR", "AAPL"]}
        )

    events = load_split_events(path=path, query=fake_query)

    assert sorted(events["security_id"]) == ["id-1", "id-2", "id-3"]
    whlr = events[events["security_id"].isin(["id-1", "id-2"])]
    assert whlr["ratio"].tolist() == pytest.approx([9.0, 9.0])
    aapl = events[events["security_id"] == "id-3"]
    assert aapl["ratio"].tolist() == pytest.approx([0.25])


def test_no_split_artifact_yields_an_empty_event_frame(tmp_path):
    from src.crispdm.portfolio import load_split_events

    events = load_split_events(
        path=tmp_path / "missing.csv", query=lambda sql, params: pd.DataFrame()
    )

    assert events.empty
    assert list(events.columns) == ["security_id", "date", "ratio"]


def test_a_series_with_no_usable_print_is_blanked_rather_than_kept_at_absurd_values():
    # The WHLR pattern in August 2024: every close is in the tens of millions.
    frame = _series("X", [7.5e7, 6.4e7, 5.7e7], volumes=[0, 0, 0])

    cleaned, rejected = clean_prices(frame)

    assert rejected == 3
    assert cleaned["close"].isna().all()


def test_the_universe_query_also_bounds_the_formation_price_from_above():
    captured = {}
    columns = [
        "security_id",
        "dividend_income_score",
        "sustainability_score",
        "appreciation_score",
        "risk_score",
        "valuation_score",
        "composite_score",
        "score_coverage",
    ]

    def fake_query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return pd.DataFrame(columns=columns)

    load_universe(pd.Timestamp("2026-10-23"), query=fake_query)

    assert "px.close <= :max_price" in captured["sql"]
    assert captured["params"]["max_price"] == pytest.approx(1e6)


def test_a_security_with_too_many_rejected_prints_is_flagged_unreliable():
    # Three of ten prints are stale (30%), above the 20% threshold.
    noisy = _series(
        "N",
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        volumes=[1000, 0, 1000, 0, 1000, 0, 1000, 1000, 1000, 1000],
    )
    clean = _series("C", [2.0] * 10, volumes=[1000] * 10)
    cleaned, _ = clean_prices(pd.concat([noisy, clean], ignore_index=True))

    assert cleaned.attrs["unreliable_ids"] == ["N"]


def test_a_security_with_a_few_rejected_prints_is_kept():
    # One of ten prints (10%) is stale: below the threshold.
    frame = _series("K", [1.0] * 10, volumes=[1000, 0] + [1000] * 8)

    cleaned, _ = clean_prices(frame)

    assert cleaned.attrs["unreliable_ids"] == []


def test_a_blanked_series_is_flagged_unreliable():
    frame = _series("X", [7.5e7, 6.4e7, 5.7e7], volumes=[0, 0, 0])

    cleaned, _ = clean_prices(frame)

    assert cleaned.attrs["unreliable_ids"] == ["X"]


def test_exclude_unreliable_drops_only_the_flagged_securities():
    frame = _series("X", [7.5e7, 6.4e7, 5.7e7], volumes=[0, 0, 0])
    cleaned, _ = clean_prices(frame)
    universe = pd.DataFrame({"security_id": ["X", "Y"], "composite_score": [0.9, 0.1]})

    kept = exclude_unreliable(universe, cleaned)

    assert kept["security_id"].tolist() == ["Y"]


def test_split_events_default_to_the_warehouse_table():
    from src.crispdm.portfolio import load_split_events

    seen = {}

    def fake_query(sql, params):
        seen["sql"] = sql
        return pd.DataFrame(
            {"security_id": ["a"], "date": [pd.Timestamp("2020-08-31").date()], "ratio": [0.25]}
        )

    events = load_split_events(query=fake_query)

    assert "raw.corporate_actions" in seen["sql"]
    assert events["ratio"].tolist() == [0.25]
    assert events["date"].iloc[0] == pd.Timestamp("2020-08-31")


def test_an_empty_corporate_actions_table_yields_an_empty_event_frame():
    from src.crispdm.portfolio import load_split_events

    events = load_split_events(query=lambda sql, params: pd.DataFrame())

    assert events.empty
    assert list(events.columns) == ["security_id", "date", "ratio"]
