from datetime import date

import pandas as pd

from src.crispdm.macro_vintages import as_of_series, rows_from_alfred


def _obs(observed, value, vintage):
    return {
        "date": observed,
        "value": value,
        "realtime_start": vintage,
        "realtime_end": "9999-12-31",
    }


def test_missing_values_and_impossible_vintages_are_dropped():
    payload = {
        "observations": [
            _obs("2024-01-01", "1.5", "2024-01-02"),
            _obs("2024-01-02", ".", "2024-01-03"),
            _obs("2024-01-03", "2.0", "2024-01-01"),  # known before it happened
            {"date": "bad"},
        ]
    }

    rows = rows_from_alfred("S", "percent", payload)

    assert [(r["observation_date"], r["value"]) for r in rows] == [(date(2024, 1, 1), 1.5)]
    assert rows[0]["vintage_date"] == date(2024, 1, 2)
    assert rows[0]["source"] == "FRED"


def test_each_revision_becomes_its_own_vintage():
    payload = {
        "observations": [
            _obs("2024-01-01", "1.0", "2024-02-01"),
            _obs("2024-01-01", "1.4", "2024-03-01"),
        ]
    }

    rows = rows_from_alfred("S", "percent", payload)

    assert [(r["vintage_date"], r["value"]) for r in rows] == [
        (date(2024, 2, 1), 1.0),
        (date(2024, 3, 1), 1.4),
    ]


def test_as_of_passes_the_series_and_date_to_the_query():
    seen = {}

    def fake(sql, params):
        seen.update(params)
        seen["sql"] = sql
        return pd.DataFrame(
            {
                "observation_date": [date(2024, 1, 1)],
                "value": [1.0],
                "vintage_date": [date(2024, 2, 1)],
            }
        )

    frame = as_of_series("S", date(2024, 2, 15), query=fake)

    assert seen["series_id"] == "S" and seen["as_of"] == date(2024, 2, 15)
    assert "vintage_date <= :as_of" in seen["sql"]
    assert frame["value"].tolist() == [1.0]


def test_an_empty_result_keeps_its_columns():
    frame = as_of_series("S", date(2024, 1, 1), query=lambda s, p: pd.DataFrame())

    assert frame.empty
    assert list(frame.columns) == ["observation_date", "value", "vintage_date"]


def test_a_window_with_too_many_vintages_is_bisected(monkeypatch):
    import io
    import json
    from urllib.error import HTTPError

    from scripts import load_macro_vintages as lmv

    windows = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, timeout=0):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(url).query)
        low, high = q["realtime_start"][0], q["realtime_end"][0]
        windows.append((low, high))
        span = (date.fromisoformat(high) - date.fromisoformat(low)).days
        if span > 1000:
            body = io.BytesIO(b'{"error_message":"exceeds the maximum number of vintage dates"}')
            raise HTTPError(url, 400, "bad", {}, body)
        return _Resp(json.dumps({"count": 0, "observations": []}).encode())

    out = lmv.fetch_vintages("X", "k", "2010-01-01", "2010-01-01", "2020-01-01", opener)

    assert len(out) >= 4
    covered = sorted(
        w for w in windows if (date.fromisoformat(w[1]) - date.fromisoformat(w[0])).days <= 1000
    )
    assert covered[0][0] == "2010-01-01" and covered[-1][1] == "2020-01-01"
    for (_, prev_end), (next_start, _) in zip(covered, covered[1:], strict=False):
        assert (date.fromisoformat(next_start) - date.fromisoformat(prev_end)).days == 1
