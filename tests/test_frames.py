from datetime import date

import pandas as pd
import pytest

from src.crispdm.frames import default_periods, peer_stats, period_code, rows_from_frame


def test_period_codes():
    assert period_code(2023) == "CY2023"
    assert period_code(2023, 4) == "CY2023Q4"
    assert period_code(2023, 4, instant=True) == "CY2023Q4I"


def test_an_instant_needs_a_quarter_and_quarters_are_bounded():
    with pytest.raises(ValueError):
        period_code(2023, instant=True)
    with pytest.raises(ValueError):
        period_code(2023, 5)


def test_default_periods_are_completed_years_only():
    assert default_periods("duration", today=date(2026, 3, 1), years=3) == [
        "CY2023",
        "CY2024",
        "CY2025",
    ]
    assert default_periods("instant", today=date(2026, 3, 1), years=2) == [
        "CY2024Q4I",
        "CY2025Q4I",
    ]


def test_frame_rows_are_one_per_filer_and_bad_rows_are_dropped():
    payload = {
        "data": [
            {"cik": 320193, "entityName": "Apple", "val": 5, "end": "2024-09-28", "accn": "a"},
            {"cik": 320193, "val": 6, "end": "2024-09-28"},
            {"cik": "x", "val": 1},
            {"cik": 1, "val": None},
        ]
    }

    rows = rows_from_frame("us-gaap", "Assets", "USD", "CY2024Q4I", payload)

    assert len(rows) == 1
    assert rows[0]["cik"] == "0000320193" and rows[0]["value"] == 6.0
    assert rows[0]["period_end"] == date(2024, 9, 28)


def test_peer_stats_returns_none_when_there_are_no_peers():
    frame = pd.DataFrame([{"peers": 0, "median": None, "p25": None, "p75": None}])

    stats = peer_stats("Assets", "CY2024Q4I", "1", query=lambda s, p: frame)

    assert stats == {"peers": 0, "median": None, "p25": None, "p75": None}


def test_peer_stats_pads_the_cik_and_passes_the_sic_prefix():
    seen = {}

    def fake(sql, params):
        seen.update(params)
        return pd.DataFrame([{"peers": 3, "median": 2.0, "p25": 1.0, "p75": 3.0}])

    stats = peer_stats("Assets", "CY2024Q4I", "320193", sic_digits=3, query=fake)

    assert seen["cik"] == "0000320193" and seen["digits"] == 3
    assert stats["median"] == 2.0 and stats["peers"] == 3
