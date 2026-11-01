from datetime import date

import pandas as pd
import pytest

from src.crispdm.identity import identifier_coverage, normalize, resolve_security_ids


def test_cik_is_zero_padded_and_others_are_upper_cased():
    assert normalize("cik", "320193") == "0000320193"
    assert normalize("ticker", " aapl ") == "AAPL"
    assert normalize("isin", "us0378331005") == "US0378331005"


def test_an_unknown_identifier_type_is_rejected():
    with pytest.raises(ValueError):
        normalize("figi", "x")


def test_resolution_passes_the_normalized_value_and_as_of_date():
    seen = {}

    def fake(sql, params):
        seen.update(params)
        return pd.DataFrame({"security_id": ["a", "b"]})

    ids = resolve_security_ids("cik", "1", as_of=date(2020, 1, 2), query=fake)

    assert ids == ["a", "b"]
    assert seen == {"id_type": "cik", "id_value": "0000000001", "as_of": date(2020, 1, 2)}


def test_an_unmatched_identifier_resolves_to_nothing():
    assert resolve_security_ids("ticker", "ZZZ", query=lambda s, p: pd.DataFrame()) == []


def test_coverage_is_returned_as_plain_ints():
    frame = pd.DataFrame(
        [{"active": 3, "with_cik": 3, "with_market_identifier": 2, "fully_identified": 2}]
    )

    assert identifier_coverage(query=lambda s, p: frame)["fully_identified"] == 2
