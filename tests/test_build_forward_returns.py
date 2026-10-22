"""The forward-return build script: how it bounds its own work.

The build reads the whole price history behind every window it writes, so the way
it splits the range is the difference between a nightly that takes four minutes and
one that takes half an hour. These tests pin the window plan rather than the build
itself, which needs a warehouse.
"""

import sys
from datetime import date

from scripts import build_forward_returns as build


def test_the_window_plan_covers_the_range_without_gaps():
    windows = build.plan_windows(date(2020, 1, 1), date(2021, 12, 31), max_rows=1_000_000)

    assert windows[0][0] == date(2020, 1, 1)
    assert windows[-1][1] == date(2022, 1, 1)
    for (_, end), (start, _) in zip(windows, windows[1:]):
        assert end == start


def test_a_range_that_fits_in_one_window_is_one_window(monkeypatch):
    monkeypatch.setattr(build, "observation_density", lambda first, last: 1_000)

    windows = build.plan_windows(date(2020, 1, 1), date(2020, 12, 31))

    assert len(windows) == 1


def test_a_dense_range_is_split_into_several(monkeypatch):
    # 365 days of dense pricing cannot fit in one window's row budget.
    monkeypatch.setattr(build, "observation_density", lambda first, last: 3_600_000)

    windows = build.plan_windows(date(2020, 1, 1), date(2020, 12, 31), max_rows=1_000_000)

    assert len(windows) > 1


def test_an_empty_price_history_plans_a_single_window(monkeypatch):
    monkeypatch.setattr(build, "observation_density", lambda first, last: 0)

    windows = build.plan_windows(date(2020, 1, 1), date(2020, 12, 31))

    assert windows == [(date(2020, 1, 1), date(2021, 1, 1))]


def test_the_window_width_floor_is_respected(monkeypatch):
    monkeypatch.setattr(build, "observation_density", lambda first, last: 10_000_000_000)

    windows = build.plan_windows(date(2020, 1, 1), date(2020, 12, 31), max_rows=1_000_000)

    span = (windows[0][1] - windows[0][0]).days
    assert span == build.MIN_WINDOW_DAYS


def test_the_fixed_window_option_splits_by_calendar_days():
    windows = build._fixed_windows(date(2020, 1, 1), date(2020, 12, 31), 100)

    assert len(windows) == 4
    assert windows[0] == (date(2020, 1, 1), date(2020, 4, 10))
    assert windows[-1][1] == date(2021, 1, 1)


def test_the_default_window_budget_is_bounded():
    assert build.MAX_WINDOW_ROWS > 0
    assert build.MIN_WINDOW_DAYS > 0
    assert build.MIN_WINDOW_DAYS <= build.MAX_WINDOW_ROWS


def test_the_incremental_build_starts_at_the_cutoff(monkeypatch):
    # A rerun after a partial run has to converge, so the floor is the earlier of
    # the cutoff and the first priced date.
    built = []

    monkeypatch.setattr(
        build,
        "observation_date_range",
        lambda: (date(2025, 1, 1), date(2026, 10, 20)),
    )
    monkeypatch.setattr(build, "observation_density", lambda first, last: 1_000)
    monkeypatch.setattr(
        build, "build_forward_returns", lambda date_from, date_to: built.append(date_from) or []
    )
    monkeypatch.setattr(build, "persist_forward_returns", lambda df: 0)
    monkeypatch.setattr(sys, "argv", ["build_forward_returns", "--days", "400"])

    assert build.main() == 0
    assert built == [date(2025, 9, 15)]


def test_a_full_build_starts_at_the_first_priced_date(monkeypatch):
    built = []

    monkeypatch.setattr(
        build,
        "observation_date_range",
        lambda: (date(2019, 1, 2), date(2026, 10, 20)),
    )
    monkeypatch.setattr(build, "observation_density", lambda first, last: 1_000)
    monkeypatch.setattr(
        build, "build_forward_returns", lambda date_from, date_to: built.append(date_from) or []
    )
    monkeypatch.setattr(build, "persist_forward_returns", lambda df: 0)
    monkeypatch.setattr(sys, "argv", ["build_forward_returns"])

    assert build.main() == 0
    assert built == [date(2019, 1, 2)]


def test_a_warehouse_with_no_prices_says_so_and_fails(monkeypatch, capsys):
    monkeypatch.setattr(build, "observation_date_range", lambda: (None, None))
    monkeypatch.setattr(sys, "argv", ["build_forward_returns"])

    assert build.main() == 1
    assert "No priced observations" in capsys.readouterr().out
