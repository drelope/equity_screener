"""Tests for walk-forward validation with purging and embargo."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.crispdm.validation import (
    WalkForwardValidator,
    embargo_split,
    no_leakage_check,
    purge_overlapping,
)


def test_walk_forward_expanding_splits():
    validator = WalkForwardValidator(
        train_window_days=756,
        test_window_days=63,
        step_days=63,
        purge_days=21,
        embargo_days=21,
        expanding=True,
    )
    splits = list(validator.split(date(2020, 1, 1), date(2023, 1, 1)))
    assert len(splits) > 0
    # Expanding should keep train start constant
    first = splits[0]
    assert first.train_start == date(2020, 1, 1)


def test_walk_forward_rolling_splits():
    validator = WalkForwardValidator(
        train_window_days=756,
        test_window_days=63,
        step_days=63,
        purge_days=21,
        embargo_days=21,
        expanding=False,
    )
    splits = list(validator.split(date(2020, 1, 1), date(2024, 1, 1)))
    assert len(splits) > 0
    # Rolling windows should move
    if len(splits) >= 2:
        assert splits[1].train_start > splits[0].train_start


def test_purge_overlapping_empty():
    df = pd.DataFrame()
    result = purge_overlapping(df, "label")
    assert result.empty


def test_purge_overlapping_drops_rows_whose_label_window_reaches_test():
    """A row dated D is labelled through D + horizon; the purge must remove it."""
    df = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=120)})
    test_start = date(2023, 3, 1)
    result = purge_overlapping(df, "label", horizon_days=63, test_start=test_start)

    assert len(result) < len(df)
    cutoff = pd.Timestamp(test_start) - pd.Timedelta(days=63)
    assert (pd.to_datetime(result["date"]) < cutoff).all()
    assert (pd.to_datetime(df["date"]) >= cutoff).any()


def test_purge_overlapping_is_a_noop_without_a_test_boundary():
    df = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=10)})
    pd.testing.assert_frame_equal(purge_overlapping(df, "label"), df)


def test_walk_forward_embargo_separates_test_from_next_train():
    validator = WalkForwardValidator(
        train_window_days=756,
        test_window_days=63,
        step_days=21,
        purge_days=21,
        embargo_days=21,
        expanding=False,
    )
    splits = list(validator.split(date(2020, 1, 1), date(2024, 1, 1)))
    assert len(splits) >= 2
    for previous, current in zip(splits, splits[1:]):
        # The embargo is the gap between the previous test block and the next
        # fold's test start (which is also its train end before the purge).
        assert current.test_start >= previous.test_end + timedelta(days=21)


def test_embargo_split_removes_recent_samples():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=100),
            "value": range(100),
        }
    )
    test_start = date(2023, 4, 1)
    result = embargo_split(df, test_start, embargo_days=21)
    # Should remove samples within 21 days before test_start
    max_date = result["date"].max().date()
    assert max_date < test_start


def test_no_leakage_check_passes_with_gap():
    train_dates = pd.Series(pd.date_range("2020-01-01", "2022-01-01"))
    test_dates = pd.Series(pd.date_range("2022-04-01", "2022-07-01"))
    assert no_leakage_check(train_dates, test_dates, label_horizon_days=63)


def test_no_leakage_check_fails_with_overlap():
    train_dates = pd.Series(pd.date_range("2020-01-01", "2022-06-01"))
    test_dates = pd.Series(pd.date_range("2022-04-01", "2022-07-01"))
    assert not no_leakage_check(train_dates, test_dates, label_horizon_days=63)
