import numpy as np
import pandas as pd
import pytest

from src.crispdm.event_study import (
    bonferroni_t,
    daily_returns,
    ex_dividend_events,
    ex_dividend_study,
    liquid_mask,
    market_return,
    opex_dispersion,
    opex_study,
    third_fridays,
)


def _bdays(start="2019-01-02", end="2026-09-30"):
    return pd.bdate_range(start, end)


def test_third_friday_is_the_third_friday():
    got = third_fridays(_bdays("2024-01-02", "2024-03-29"))

    assert [d.strftime("%Y-%m-%d") for d in got] == ["2024-01-19", "2024-02-16", "2024-03-15"]


def test_a_holiday_third_friday_falls_back_to_the_prior_trading_day():
    # 2019-04-19 was Good Friday: the market was closed, so opex was Thursday the 18th.
    days = _bdays("2019-04-01", "2019-04-30").difference(pd.DatetimeIndex(["2019-04-19"]))

    assert pd.Timestamp("2019-04-18") in third_fridays(days)
    assert pd.Timestamp("2019-04-19") not in third_fridays(days)


def test_returns_blank_low_priced_and_absurd_prints():
    idx = _bdays("2024-01-02", "2024-01-05")
    close = pd.DataFrame(
        {"a": [10, 11, 100, 101], "pen": [1, 1.1, 1.2, 1.3]}, index=idx, dtype=float
    )

    ret = daily_returns(close)

    assert ret["pen"].isna().all()  # prior close under the floor
    assert np.isnan(ret["a"].iloc[2])  # +809% is a bad print
    assert ret["a"].iloc[1] == pytest.approx(0.1)


def _market_with_opex_effect(effect, seed=0):
    rng = np.random.default_rng(seed)
    days = _bdays()
    opex = third_fridays(days)
    ret = pd.Series(rng.normal(0.0004, 0.01, len(days)), index=days)
    ret[ret.index.isin(opex)] += effect
    return ret, opex


def test_a_planted_opex_effect_is_detected():
    market, opex = _market_with_opex_effect(0.01)

    stats = {s.offset: s for s in opex_study(market, opex)}

    assert stats[0].n > 80
    assert stats[0].t > bonferroni_t(10)
    assert abs(stats[3].t) < bonferroni_t(10)  # an unaffected offset stays quiet


def test_pure_noise_shows_no_opex_effect():
    market, opex = _market_with_opex_effect(0.0, seed=3)

    stats = opex_study(market, opex)

    assert max(abs(s.t) for s in stats if s.t is not None) < bonferroni_t(len(stats)) + 0.5


def test_opex_dispersion_flags_a_volatility_spike():
    rng = np.random.default_rng(1)
    days = _bdays()
    opex = third_fridays(days)
    ret = pd.Series(rng.normal(0, 0.01, len(days)), index=days)
    ret[ret.index.isin(opex)] *= 3

    out = opex_dispersion(ret, opex)

    assert out["opex_mean_abs"] > out["other_mean_abs"] and out["t"] > 4


def _ex_fixture(drop_fraction):
    idx = _bdays("2024-01-02", "2024-03-29")
    rng = np.random.default_rng(7)
    base = pd.DataFrame(
        {f"s{i}": 50 * np.cumprod(1 + rng.normal(0, 0.0002, len(idx))) for i in range(40)},
        index=idx,
    )
    ex = idx[30]
    amount = 0.5
    base.loc[ex:, "s0"] = base.loc[ex:, "s0"] - amount * drop_fraction
    events = pd.DataFrame({"security_id": ["s0"], "ex_date": [ex], "amount": [amount]})
    return base, events


def test_a_stock_that_drops_exactly_its_dividend_has_ratio_one_and_no_abnormal_return():
    close, events = _ex_fixture(1.0)
    ret = daily_returns(close)
    out = ex_dividend_events(close, ret, market_return(ret), events)

    assert out["drop_ratio"].iloc[0] == pytest.approx(1.0, abs=0.15)
    assert abs(out[0].iloc[0]) < 0.01  # total return is about the market's


def test_a_stock_that_does_not_drop_has_ratio_zero_and_a_positive_abnormal_return():
    close, events = _ex_fixture(0.0)
    ret = daily_returns(close)
    out = ex_dividend_events(close, ret, market_return(ret), events)

    assert out["drop_ratio"].iloc[0] == pytest.approx(0.0, abs=0.15)
    assert out[0].iloc[0] > 0.005  # the dividend added back with no price fall


def test_events_too_close_to_the_data_edge_or_low_priced_are_dropped():
    idx = _bdays("2024-01-02", "2024-02-29")
    close = pd.DataFrame(
        {"a": np.linspace(50, 51, len(idx)), "p": np.linspace(2, 2.1, len(idx))}, index=idx
    )
    ret = daily_returns(close)
    events = pd.DataFrame(
        {
            "security_id": ["a", "a", "p"],
            "ex_date": [idx[1], idx[-2], idx[20]],  # too early, too late, under $5
            "amount": [0.3, 0.3, 0.05],
        }
    )

    assert ex_dividend_events(close, ret, market_return(ret), events).empty


def test_ex_dividend_study_clusters_by_date_and_reports_cumulative_windows():
    rng = np.random.default_rng(2)
    rows = []
    for date in pd.bdate_range("2024-01-02", periods=30):
        for sec in range(5):
            row = {"security_id": f"s{sec}", "ex_date": date, "drop_ratio": 0.8, "yield": 0.01}
            row.update({k: rng.normal(0, 0.005) for k in range(-5, 6)})
            row[1] += 0.01  # planted post-ex drift
            rows.append(row)

    study = ex_dividend_study(pd.DataFrame(rows))

    assert study["n"] == 150 and study["dates"] == 30  # tested across dates, not events
    assert study["cumulative"]["CAR[+1,+5]"]["t"] > 3
    assert abs(study["cumulative"]["CAR[-5,-1]"]["t"]) < 3
    assert study["drop_ratio"]["median"] == pytest.approx(0.8)


def test_empty_events_give_an_empty_study():
    assert ex_dividend_study(pd.DataFrame())["n"] == 0


def test_liquid_mask_keeps_the_top_by_dollar_volume():
    idx = _bdays("2024-01-02", periods=70) if False else pd.bdate_range("2024-01-02", periods=70)
    close = pd.DataFrame({"big": 100.0, "mid": 100.0, "tiny": 100.0}, index=idx)
    volume = pd.DataFrame({"big": 1e6, "mid": 1e5, "tiny": 1e3}, index=idx)

    mask = liquid_mask(close, volume, top=2, window=20)

    assert mask["big"].iloc[-1] and mask["mid"].iloc[-1] and not mask["tiny"].iloc[-1]


def test_bonferroni_threshold_grows_with_the_number_of_tests():
    assert bonferroni_t(1) == pytest.approx(1.96, abs=0.01)
    assert bonferroni_t(10) > bonferroni_t(1)


def test_payer_mask_covers_the_lookback_after_an_ex_date_only():
    from src.crispdm.event_study import payer_mask

    idx = pd.bdate_range("2024-01-02", periods=400)
    cols = pd.Index(["a", "b"])
    events = pd.DataFrame({"security_id": ["a"], "ex_date": [idx[10]]})

    mask = payer_mask(idx, cols, events, lookback_days=100)

    assert not mask["a"].iloc[9] and mask["a"].iloc[10] and mask["a"].iloc[110]
    assert not mask["a"].iloc[111]
    assert not mask["b"].any()


def test_an_event_with_an_oversized_dividend_is_dropped():
    close, events = _ex_fixture(1.0)
    events["amount"] = 8.0  # 16% of a $50 stock
    ret = daily_returns(close)

    assert ex_dividend_events(close, ret, market_return(ret), events).empty


def test_winsorizing_stops_a_few_corrupt_events_from_moving_the_mean():
    from src.crispdm.event_study import winsorize

    values = pd.Series([0.001] * 98 + [5.0, -5.0])  # one outlier in each 1% tail

    assert winsorize(values).abs().max() < 1.0
    assert winsorize(pd.Series([1.0, 2.0])).tolist() == [1.0, 2.0]  # too few to clip


def test_the_study_is_not_driven_by_outliers():
    rng = np.random.default_rng(4)
    rows = []
    for date in pd.bdate_range("2024-01-02", periods=40):
        for sec in range(30):
            row = {"security_id": f"s{sec}", "ex_date": date, "drop_ratio": 0.8, "yield": 0.01}
            row.update({k: rng.normal(0, 0.005) for k in range(-5, 6)})
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame.loc[0, 0] = 50.0  # one absurd day-0 abnormal return

    assert abs(ex_dividend_study(frame)["cumulative"]["AR[0]"]["mean"]) < 0.005
