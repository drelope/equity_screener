"""Walk-forward arithmetic on synthetic prices where the answer is known by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.crispdm.backtest import rebalance_schedule, run_walk_forward

DAYS = pd.bdate_range("2026-01-05", periods=7)  # DAYS[0] .. DAYS[6]


def _prices(closes: dict[str, list[float]]) -> pd.DataFrame:
    rows = []
    for sid, series in closes.items():
        for day, close in zip(DAYS, series):
            rows.append({"security_id": sid, "observation_date": day, "close": close})
    return pd.DataFrame(rows)


def _universe(scores: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": list(scores),
            "composite_score": list(scores.values()),
            "score_coverage": 1.0,
        }
    )


def _run(closes, scores_by_date, dates, **kwargs):
    prices = _prices(closes)

    def prices_for(ids, start, end):
        return prices[prices["security_id"].isin(ids)]

    return run_walk_forward(
        dates,
        universe_for=lambda day: _universe(scores_by_date[pd.Timestamp(day)]),
        prices_for=prices_for,
        long_count=1,
        short_count=1,
        **kwargs,
    )


def test_holding_periods_chain_and_never_earn_the_formation_day_return_of_the_next_book():
    # A rises 10% on DAYS[1] and DAYS[2]. B jumps 10% on DAYS[3], the first rebalance.
    closes = {
        "A": [100, 110, 121, 121, 121, 121, 121],
        "B": [100, 100, 100, 110, 110, 121, 121],
    }
    scores = {
        DAYS[0]: {"A": 0.9, "B": 0.1},  # period 1: long A, short B
        DAYS[3]: {"A": 0.1, "B": 0.9},  # period 2: long B, short A
    }

    result = _run(closes, scores, [DAYS[0], DAYS[3], DAYS[6]])

    # Period 1 (DAYS[0]..DAYS[3]): long A earns +10%, +10%, 0; short B loses 5% on DAYS[3].
    assert result.daily.loc[DAYS[3], "return"] == pytest.approx(-0.05)
    period_one = (1.10) * (1.10) * (1 - 0.05) - 1
    # Period 2 (DAYS[3]..DAYS[6]): long B earns +10% on DAYS[5]; the DAYS[3] jump is not ours.
    period_two = 0.10
    assert result.periods["period_return"].tolist() == pytest.approx([period_one, period_two])
    assert result.daily.loc[DAYS[4], "return"] == pytest.approx(0.0)
    assert result.daily.loc[DAYS[5], "return"] == pytest.approx(0.10)


def test_turnover_counts_the_opening_buy_and_the_full_flip():
    closes = {
        "A": [100, 110, 121, 121, 121, 121, 121],
        "B": [100, 100, 100, 110, 110, 121, 121],
    }
    scores = {
        DAYS[0]: {"A": 0.9, "B": 0.1},
        DAYS[3]: {"A": 0.1, "B": 0.9},
    }

    result = _run(closes, scores, [DAYS[0], DAYS[3], DAYS[6]])

    # Opening: |1.0| + |-0.5| = 1.5 traded, one-way turnover 0.75.
    # Flip: A 1.0 -> -0.5 and B -0.5 -> 1.0, 3.0 traded, one-way turnover 1.5.
    assert result.periods["turnover"].tolist() == pytest.approx([0.75, 1.5])
    assert result.metrics["held_periods"] == 2


def test_a_period_with_too_few_names_is_held_in_cash_and_recorded():
    closes = {"A": [100, 110, 121, 121, 121, 121, 121]}
    scores = {
        DAYS[0]: {"A": 0.9},  # one name cannot fill a long and a short sleeve
        DAYS[3]: {"A": 0.9},
    }

    result = _run(closes, scores, [DAYS[0], DAYS[3]])

    assert result.periods.loc[0, "status"].startswith("cash:")
    assert result.daily["return"].abs().sum() == pytest.approx(0.0)
    assert result.metrics["cash_periods"] == 1
    assert result.metrics["held_periods"] == 0


def test_at_least_two_rebalance_dates_are_required():
    with pytest.raises(ValueError):
        run_walk_forward([DAYS[0]], lambda day: pd.DataFrame(), lambda *args: pd.DataFrame())


def test_rebalance_schedule_takes_the_last_score_date_of_each_month_and_the_newest_date():
    dates = ["2026-01-02", "2026-01-30", "2026-02-27", "2026-03-02", "2026-03-13"]

    schedule = rebalance_schedule(dates)

    assert list(schedule) == [
        pd.Timestamp("2026-01-30"),
        pd.Timestamp("2026-02-27"),
        pd.Timestamp("2026-03-13"),
    ]
    assert np.all(np.diff(schedule.asi8) > 0)
