"""Walk-forward validation with purging and embargo to prevent leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

import pandas as pd


@dataclass
class TimeSplit:
    """A single train/test split for time-series validation."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date
    purge_days: int = 0
    embargo_days: int = 0


class WalkForwardValidator:
    """Walk-forward validation with purging and embargo."""

    def __init__(
        self,
        train_window_days: int = 756,  # ~3 years
        test_window_days: int = 63,  # ~3 months
        step_days: int = 63,  # rolling step
        purge_days: int = 21,  # purge overlapping labels
        embargo_days: int = 21,  # embargo after test
        expanding: bool = False,
    ):
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days
        self.step_days = step_days
        self.purge_days = purge_days
        self.embargo_days = embargo_days
        self.expanding = expanding

    def split(self, start_date: date, end_date: date) -> Iterator[TimeSplit]:
        """Generate walk-forward splits."""
        if self.expanding:
            train_start = start_date
            current = start_date + timedelta(days=self.train_window_days)
        else:
            current = start_date + timedelta(days=self.train_window_days)

        while current + timedelta(days=self.test_window_days) <= end_date:
            if self.expanding:
                train_s = train_start
            else:
                train_s = current - timedelta(days=self.train_window_days)
            train_e = current - timedelta(days=self.purge_days)
            test_s = current
            test_e = current + timedelta(days=self.test_window_days)

            yield TimeSplit(
                train_start=train_s,
                train_end=train_e,
                test_start=test_s,
                test_end=test_e,
                purge_days=self.purge_days,
                embargo_days=self.embargo_days,
            )

            # Advance to the next fold. The step may be shorter than the test
            # window (overlapping test blocks), but a fold must never start
            # before the previous test plus the embargo: that gap is the whole
            # point of an embargo, and silently ignoring it is how a validator
            # reports "no leakage" while handing the model adjacent data.
            next_current = current + timedelta(days=self.step_days)
            earliest = test_e + timedelta(days=self.embargo_days)
            current = max(next_current, earliest)


def purge_overlapping(
    df: pd.DataFrame,
    label_col: str,
    date_col: str = "date",
    horizon_days: int = 63,
    test_start: date | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Drop training rows whose label window reaches into the test period.

    A row dated ``D`` is labelled from events up to ``D + horizon_days``. If
    that window touches or passes ``test_start`` the row's label was computed
    with information the test set is supposed to be blind to, so training on it
    leaks the future. Keep only rows whose label window ends strictly before
    the test period begins.

    ``test_start`` is required for the purge to do anything; without a test
    boundary there is nothing to purge against, so the frame is returned
    unchanged. (An earlier implementation returned the frame unchanged *always*,
    which made the module's "purging" claim false.)
    """
    if df.empty or test_start is None:
        return df
    df = df.copy()
    dates = pd.to_datetime(df[date_col])
    cutoff = pd.Timestamp(test_start) - pd.Timedelta(days=horizon_days)
    return df[dates < cutoff]


def embargo_split(
    train_df: pd.DataFrame,
    test_start: date,
    embargo_days: int,
    date_col: str = "date",
) -> pd.DataFrame:
    """Remove training samples in embargo period before test starts."""
    if train_df.empty or embargo_days <= 0:
        return train_df
    train_df = train_df.copy()
    train_df[date_col] = pd.to_datetime(train_df[date_col])
    embargo_cutoff = pd.Timestamp(test_start) - timedelta(days=embargo_days)
    return train_df[train_df[date_col] < embargo_cutoff]


def no_leakage_check(
    train_dates: pd.Series,
    test_dates: pd.Series,
    label_horizon_days: int = 63,
) -> bool:
    """Verify no temporal leakage between train and test sets."""
    if train_dates.empty or test_dates.empty:
        return True
    train_max = pd.to_datetime(train_dates).max()
    test_min = pd.to_datetime(test_dates).min()
    # Ensure test starts after train ends with sufficient gap
    return test_min >= train_max + timedelta(days=label_horizon_days)
