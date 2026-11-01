import pandas as pd
import pytest

from scripts.load_corporate_actions import SOURCE, split_rows


def _securities():
    return pd.DataFrame(
        {"security_id": ["id-1", "id-2", "id-3"], "ticker": ["WHLR", "WHLR", "AAPL"]}
    )


def _raw():
    return pd.DataFrame(
        {
            "ticker": ["WHLR", "AAPL", "ZZZ", "BAD"],
            "date": ["2026-09-22", "2020-08-31", "2020-01-01", "2020-01-01"],
            "numerator": [1, 4, 2, None],
            "denominator": [9, 1, 1, None],
        }
    )


def test_ratio_is_denominator_over_numerator_and_invalid_rows_are_dropped():
    rows = split_rows(_raw(), _securities())

    assert {r["ticker"] for r in rows} == {"WHLR", "AAPL", "ZZZ"}
    aapl = next(r for r in rows if r["ticker"] == "AAPL")
    assert aapl["ratio"] == pytest.approx(0.25)
    assert aapl["source"] == SOURCE


def test_a_shared_ticker_yields_one_distinct_row_per_identity():
    rows = [r for r in split_rows(_raw(), _securities()) if r["ticker"] == "WHLR"]

    assert sorted(r["security_id"] for r in rows) == ["id-1", "id-2"]
    assert len({r["source_hash"] for r in rows}) == 2


def test_an_unmatched_ticker_is_kept_with_a_null_security():
    zzz = next(r for r in split_rows(_raw(), _securities()) if r["ticker"] == "ZZZ")

    assert zzz["security_id"] is None


def test_reloading_the_same_file_produces_identical_hashes():
    first = [r["source_hash"] for r in split_rows(_raw(), _securities())]
    second = [r["source_hash"] for r in split_rows(_raw(), _securities())]

    assert first == second
