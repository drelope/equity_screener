"""A price series that mostly does not trade is not a price history.

CMCT printed $350 to $3,725 to $214 to $6.10 on a median 11 shares a day. The jumps persisted,
so the spike-and-revert test kept them, and a short in it cost 14% in one month and the
collapse later returned a false gain. Thin volume plus a violent move marks the series
unreliable; thin but stable and liquid but jumpy series are left alone.
"""

import numpy as np
import pandas as pd

from src.crispdm import portfolio as pf


def _series(sid, closes, volumes):
    days = pd.bdate_range("2024-12-02", periods=len(closes))
    return pd.DataFrame(
        {"security_id": sid, "observation_date": days, "close": closes, "volume": volumes}
    )


def _flagged(*frames):
    cleaned, _ = pf.clean_prices(pd.concat(frames, ignore_index=True))
    return set(cleaned.attrs["unreliable_ids"])


def test_a_thin_series_with_a_persistent_violent_jump_is_unreliable():
    closes = [350.0] * 10 + [3725.0] * 10  # a persistent 10x jump: not reverted
    thin = _series("thin", closes, [11.0] * 20)

    assert _flagged(thin) == {"thin"}


def test_a_thin_but_stable_series_is_not_flagged():
    stable = _series("stable", [10.0 + 0.01 * i for i in range(20)], [5.0] * 20)

    assert _flagged(stable) == set()


def test_a_liquid_series_with_a_real_jump_is_not_flagged():
    """A genuine 80% takeover-style move on heavy volume is a price, not noise."""
    liquid = _series("liquid", [10.0] * 10 + [18.0] * 10, [2_000_000.0] * 20)

    assert _flagged(liquid) == set()


def test_unknown_volume_is_not_treated_as_thin():
    unknown = _series("unknown", [350.0] * 10 + [3725.0] * 10, [np.nan] * 20)

    assert _flagged(unknown) == set()


def test_the_threshold_is_on_the_median_so_one_busy_day_does_not_hide_a_thin_series():
    volumes = [11.0] * 19 + [900_000.0]
    thin = _series("thin", [350.0] * 10 + [3725.0] * 10, volumes)

    assert _flagged(thin) == {"thin"}


def test_flagged_securities_are_dropped_from_the_universe_but_closes_are_unchanged():
    frame = _series("thin", [350.0] * 10 + [3725.0] * 10, [11.0] * 20)
    cleaned, _ = pf.clean_prices(frame)
    universe = pd.DataFrame({"security_id": ["thin", "ok"], "composite_score": [1.0, 2.0]})

    assert pf.exclude_unreliable(universe, cleaned)["security_id"].tolist() == ["ok"]
    assert cleaned["close"].tolist() == frame["close"].tolist()
