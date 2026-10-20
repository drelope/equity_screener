"""Dividends come from FMP first with a per-symbol Yahoo Finance fallback."""

import pandas as pd
import pytest

openbb_client = pytest.importorskip("src.crispdm.openbb_client")


class _Response:
    def __init__(self, frame=None):
        self.frame = pd.DataFrame() if frame is None else frame

    def to_dataframe(self):
        return self.frame.copy()


def _capture(monkeypatch, fmp_key=None, answers=None):
    """Patch obb; ``answers`` maps provider -> DataFrame or Exception."""
    from types import SimpleNamespace

    calls = []
    answers = answers or {}

    def fake_dividends(**kwargs):
        calls.append(kwargs)
        answer = answers.get(kwargs["provider"])
        if isinstance(answer, Exception):
            raise answer
        return _Response(answer)

    # obb builds its command tree on attribute access, so patch the whole handle.
    fake = SimpleNamespace(
        equity=SimpleNamespace(fundamental=SimpleNamespace(dividends=fake_dividends)),
        user=SimpleNamespace(credentials=SimpleNamespace(fmp_api_key=fmp_key)),
    )
    monkeypatch.setattr(openbb_client, "obb", fake)
    monkeypatch.setattr(openbb_client.settings, "openbb_provider", None)
    monkeypatch.setattr(openbb_client, "_yahoo_history", lambda symbol: (None, None))
    return calls


EVENTS = pd.DataFrame({"ex_dividend_date": ["2025-03-01"], "amount": [0.25]})


def test_without_an_fmp_key_dividends_come_from_yahoo_finance(monkeypatch):
    calls = _capture(monkeypatch, answers={"yfinance": EVENTS})

    frame = openbb_client.dividends("ABR-PD", "2025-01-01")

    assert [c["provider"] for c in calls] == ["yfinance"]
    assert "end_date" not in calls[0], "announced future ex-dates must not be cut off"
    assert frame.attrs["feed"] == "yfinance"


def test_fmp_is_preferred_when_its_key_is_loaded(monkeypatch):
    calls = _capture(monkeypatch, fmp_key="k", answers={"fmp": EVENTS, "yfinance": EVENTS})

    frame = openbb_client.dividends("KO", "2025-01-01")

    assert [c["provider"] for c in calls] == ["fmp"]
    assert frame.attrs["feed"] == "fmp"


@pytest.mark.parametrize("fmp_answer", [None, RuntimeError("Results not found.")])
def test_yahoo_finance_fills_in_when_fmp_is_empty_or_fails(monkeypatch, fmp_answer):
    calls = _capture(monkeypatch, fmp_key="k", answers={"fmp": fmp_answer, "yfinance": EVENTS})

    frame = openbb_client.dividends("GFIOF", "2025-01-01")

    assert [c["provider"] for c in calls] == ["fmp", "yfinance"]
    assert frame.attrs["feed"] == "yfinance"
    assert len(frame) == 1


def test_no_events_anywhere_is_an_empty_frame_not_an_error(monkeypatch):
    _capture(monkeypatch, fmp_key="k", answers={"fmp": RuntimeError("x")})

    assert openbb_client.dividends("NONE", "2025-01-01").empty


def test_every_provider_failing_raises_the_last_error(monkeypatch):
    _capture(
        monkeypatch,
        fmp_key="k",
        answers={"fmp": RuntimeError("fmp"), "yfinance": RuntimeError("yahoo")},
    )

    with pytest.raises(RuntimeError, match="yahoo"):
        openbb_client.dividends("BAD", "2025-01-01")


def test_an_explicit_provider_setting_still_wins(monkeypatch):
    calls = _capture(monkeypatch, fmp_key="k", answers={"yfinance": EVENTS})
    monkeypatch.setattr(openbb_client.settings, "openbb_provider", "yfinance")

    openbb_client.dividends("KO", "2025-01-01", "2026-01-01")

    assert [c["provider"] for c in calls] == ["yfinance"]
    assert calls[0]["end_date"] == "2026-01-01"


def test_fmp_amounts_are_restated_by_the_split_factors_the_closes_use(monkeypatch):
    """SF: FMP's adjDividend stays 0.46 after the 3-for-2; the closes are restated."""
    from datetime import date

    fmp = pd.DataFrame(
        {
            "ex_dividend_date": ["2025-03-03", "2026-03-02"],
            "amount": [0.46, 0.34],
            "adjusted_amount": [0.46, 0.34],
        }
    )
    _capture(monkeypatch, fmp_key="k", answers={"fmp": fmp})
    monkeypatch.setattr(
        openbb_client, "_yahoo_history", lambda symbol: ({date(2026, 2, 27): 1.5}, [])
    )

    frame = openbb_client.dividends("SF", "2025-01-01")

    assert frame["amount"].tolist() == [0.46, 0.34], "the declared amount is kept"
    assert frame["adjusted_amount"].tolist() == pytest.approx([0.46 / 1.5, 0.34])


def test_a_reverse_split_raises_the_restated_amount_and_none_keeps_fmps(monkeypatch):
    from datetime import date

    fmp = pd.DataFrame(
        {"ex_dividend_date": ["2025-04-01"], "amount": [0.05], "adjusted_amount": [0.05]}
    )
    restated = openbb_client._price_basis_adjust(fmp, {date(2026, 10, 6): 0.1})
    assert restated["adjusted_amount"].tolist() == pytest.approx([0.5])  # GPMT 1-for-10

    unchanged = openbb_client._price_basis_adjust(fmp, None)
    assert unchanged["adjusted_amount"].tolist() == [0.05]


def test_yahoo_rows_are_not_restated(monkeypatch):
    from datetime import date

    _capture(monkeypatch, answers={"yfinance": EVENTS})
    monkeypatch.setattr(
        openbb_client, "_yahoo_history", lambda symbol: ({date(2026, 1, 1): 2.0}, [])
    )

    frame = openbb_client.dividends("KO", "2025-01-01")

    assert "adjusted_amount" not in frame.columns, "Yahoo amounts are already restated"


def _fmp_events(*rows):
    return pd.DataFrame(
        [{"ex_dividend_date": ex, "amount": a, "adjusted_amount": a} for ex, a in rows]
    )


def _polygon(events):
    calls = []

    def ask():
        calls.append(1)
        return events

    return ask, calls


def test_polygon_confirming_yahoo_replaces_fmps_amount():
    """CHA: the 6-K declares US$0.92 per ADS; FMP has 0.87, Yahoo and Polygon 0.92."""
    from datetime import date

    ask, calls = _polygon([(date(2025, 12, 8), 0.92, "USD")])
    frame, checks = openbb_client.reconcile_amounts(
        _fmp_events(("2025-12-08", 0.87)), [(date(2025, 12, 8), 0.92)], {}, ask
    )

    assert frame["amount"].tolist() == [0.92]
    assert frame["adjusted_amount"].tolist() == [0.92]
    assert frame["amount_feed"].tolist() == ["yfinance"]
    assert checks == [
        {
            "ex_dividend_date": date(2025, 12, 8),
            "fmp_amount": 0.87,
            "yahoo_amount": 0.92,
            "polygon_amount": 0.92,
            "polygon_currency": "USD",
            "chosen": "yfinance",
        }
    ]
    assert calls == [1]


def test_one_yahoo_payment_fmp_lists_in_parts_is_left_alone():
    """CMBT: FMP 0.44 and 0.20 a day apart, Yahoo and Polygon one 0.64 payment."""
    from datetime import date

    ask, calls = _polygon([(date(2026, 6, 2), 0.64, "USD")])
    frame, checks = openbb_client.reconcile_amounts(
        _fmp_events(("2026-06-02", 0.44), ("2026-06-03", 0.20)),
        [(date(2026, 6, 2), 0.64)],
        {},
        ask,
    )

    assert frame["amount"].tolist() == [0.44, 0.20]
    assert frame["amount_feed"].tolist() == ["fmp", "fmp"]
    assert checks == [] and calls == []


@pytest.mark.parametrize(
    ("polygon_events", "chosen"),
    [
        ([(20251211, 0.5354, "USD")], "fmp"),  # TSM: Polygon matches FMP
        ([(20251211, 0.3063, "CAD")], "unresolved"),  # FORFF: only a local-currency figure
        ([], "unresolved"),  # Polygon has nothing
        (None, "unresolved"),  # Polygon unreachable or no key
    ],
)
def test_fmp_is_kept_unless_polygon_confirms_yahoo(polygon_events, chosen):
    from datetime import date, datetime

    if polygon_events:
        polygon_events = [
            (datetime.strptime(str(d), "%Y%m%d").date(), a, c) for d, a, c in polygon_events
        ]
    ask, _ = _polygon(polygon_events)
    frame, checks = openbb_client.reconcile_amounts(
        _fmp_events(("2025-12-11", 0.535)), [(date(2025, 12, 11), 0.684)], {}, ask
    )

    assert frame["amount"].tolist() == [0.535]
    assert frame["amount_feed"].tolist() == ["fmp"]
    assert [c["chosen"] for c in checks] == [chosen]


def test_agreement_rounding_and_splits_never_ask_polygon():
    from datetime import date

    ask, calls = _polygon([])
    fmp = _fmp_events(("2025-03-03", 0.46), ("2025-06-02", 0.0075), ("2025-09-02", 0.53))
    yahoo = [
        (date(2025, 3, 3), 0.3067),  # SF: Yahoo restated for the 3-for-2
        (date(2025, 6, 3), 0.008),  # GROW: Yahoo rounds to 3 decimals; a day apart
        (date(2025, 9, 2), 0.53),
    ]
    splits = {date(2025, 4, 1): 1.5}
    restated = openbb_client._price_basis_adjust(fmp, splits)

    frame, checks = openbb_client.reconcile_amounts(restated, yahoo, splits, ask)

    assert checks == [] and calls == []
    assert frame["amount"].tolist() == [0.46, 0.0075, 0.53]


def test_a_cached_verdict_is_reused_and_polygon_is_asked_once():
    from datetime import date

    ask, calls = _polygon([(date(2025, 4, 1), 1.03, "USD"), (date(2026, 4, 1), 1.10, "USD")])
    cached = {date(2025, 4, 1): {"fmp_amount": 0.598, "yahoo_amount": 0.989, "chosen": "yfinance"}}
    frame, checks = openbb_client.reconcile_amounts(
        _fmp_events(("2025-04-01", 0.598), ("2026-04-01", 0.70), ("2026-10-01", 0.60)),
        [(date(2025, 4, 1), 0.989), (date(2026, 4, 1), 1.08), (date(2026, 10, 1), 1.0)],
        {},
        ask,
        cached,
    )

    assert frame["amount_feed"].tolist() == ["yfinance", "yfinance", "fmp"]
    assert [c["ex_dividend_date"] for c in checks] == [date(2026, 4, 1), date(2026, 10, 1)]
    assert calls == [1], "Polygon is read once per symbol"


def test_a_cached_verdict_for_different_amounts_is_not_reused():
    from datetime import date

    ask, calls = _polygon([(date(2025, 4, 1), 0.60, "USD")])
    cached = {date(2025, 4, 1): {"fmp_amount": 0.5, "yahoo_amount": 0.989, "chosen": "yfinance"}}
    frame, checks = openbb_client.reconcile_amounts(
        _fmp_events(("2025-04-01", 0.598)), [(date(2025, 4, 1), 0.989)], {}, ask, cached
    )

    assert frame["amount_feed"].tolist() == ["fmp"]
    assert [c["chosen"] for c in checks] == ["fmp"] and calls == [1]


def test_dividends_reconciles_fmp_and_returns_new_verdicts(monkeypatch):
    from datetime import date

    _capture(monkeypatch, fmp_key="k", answers={"fmp": _fmp_events(("2025-12-08", 0.87))})
    monkeypatch.setattr(
        openbb_client, "_yahoo_history", lambda symbol: ({}, [(date(2025, 12, 8), 0.92)])
    )
    asked = []
    monkeypatch.setattr(
        openbb_client,
        "polygon_dividends",
        lambda symbol, since: asked.append((symbol, since)) or [(date(2025, 12, 8), 0.92, "USD")],
    )

    frame = openbb_client.dividends("CHA", "2025-01-01")

    assert asked == [("CHA", date(2025, 12, 4))]
    assert frame["amount"].tolist() == [0.92]
    assert [c["chosen"] for c in frame.attrs["amount_checks"]] == ["yfinance"]


def test_polygon_events_are_parsed_with_currency(monkeypatch):
    import io
    import json

    monkeypatch.setattr(openbb_client, "_direct_keys", {"polygon_api_key": "k"})
    monkeypatch.setattr(openbb_client, "_polygon_calls", openbb_client.deque())
    seen = []

    def opener(url, timeout):
        seen.append(url)
        body = {
            "results": [
                {"ex_dividend_date": "2025-12-08", "cash_amount": 0.92, "currency": "USD"},
                {"ex_dividend_date": "2026-05-27", "cash_amount": 10, "currency": "MXN"},
                {"ex_dividend_date": None, "cash_amount": 1},
                {"ex_dividend_date": "2025-11-12", "cash_amount": 0.40, "currency": "USD"},
                {"ex_dividend_date": "2025-11-12", "cash_amount": 0.07, "currency": "USD"},
            ]
        }
        return io.BytesIO(json.dumps(body).encode())

    from datetime import date

    events = openbb_client.polygon_dividends("PBR-A", "2025-01-01", opener=opener)

    assert events == [
        (date(2025, 12, 8), 0.92, "USD"),
        (date(2026, 5, 27), 10.0, "MXN"),
        (date(2025, 11, 12), pytest.approx(0.47), "USD"),  # HTGC base + supplemental
    ]
    assert "ticker=PBR.A" in seen[0]

    monkeypatch.setattr(openbb_client, "_direct_keys", {})
    monkeypatch.setattr(openbb_client, "obb", None)
    assert openbb_client.polygon_dividends("X", "2025-01-01", opener=opener) is None


VALIDATION_ERROR = RuntimeError(
    "[Error] -> 1 validations error(s) [Data Model] FMPHistoricalDividendsData "
    "[Arg] record_date -> input:  -> Input should be a valid date or datetime, "
    "input is too short"
)


def test_an_fmp_payload_openbb_rejects_is_read_directly(monkeypatch):
    """CAT/ASB-PF: FMP sends '' for unknown dates and OpenBB's model refuses them."""
    calls = _capture(monkeypatch, fmp_key="k", answers={"fmp": VALIDATION_ERROR})
    seen = []
    monkeypatch.setattr(
        openbb_client,
        "_fmp_rest_dividends",
        lambda *args: seen.append(args) or EVENTS.copy(),
    )

    frame = openbb_client.dividends("CAT", "2025-01-01")

    assert seen == [("CAT", "2025-01-01", None)]
    assert [c["provider"] for c in calls] == ["fmp"], "Yahoo must not be asked"
    assert frame.attrs["feed"] == "fmp"


def test_an_fmp_rate_limit_is_waited_out_not_sent_to_yahoo(monkeypatch):
    attempts = []
    limit = RuntimeError('Unauthorized FMP request -> 429 -> {"Error Message": "Limit Reach ."}')

    def fmp(**kwargs):
        attempts.append(kwargs["provider"])
        if len(attempts) == 1:
            raise limit
        return _Response(EVENTS)

    _capture(monkeypatch, fmp_key="k")
    openbb_client.obb.equity.fundamental.dividends = fmp
    sleeps = []
    monkeypatch.setattr(openbb_client.time, "sleep", sleeps.append)

    frame = openbb_client.dividends("ATMU", "2025-01-01")

    assert attempts == ["fmp", "fmp"]
    assert sleeps == [60]
    assert frame.attrs["feed"] == "fmp"


def test_fmp_calls_are_paced_under_the_per_minute_limit(monkeypatch):
    monkeypatch.setattr(openbb_client, "_fmp_calls", openbb_client.deque())
    monkeypatch.setattr(openbb_client, "FMP_CALLS_PER_MINUTE", 2)
    now = [100.0]
    slept = []

    def sleep(seconds):
        slept.append(round(seconds, 1))
        now[0] += seconds

    for _ in range(3):
        openbb_client._fmp_throttle(clock=lambda: now[0], sleep=sleep)

    assert slept == [60.1], "the third call waits for the first to leave the window"


def test_the_direct_fmp_read_matches_openbb_columns_and_window(monkeypatch):
    import io
    import json

    payload = [
        {
            "symbol": "CAT",
            "date": "2026-10-26",
            "recordDate": "2026-10-26",
            "paymentDate": "",
            "declarationDate": "",
            "adjDividend": 1.63,
            "dividend": 1.63,
            "yield": 1.08,
            "frequency": "Quarterly",
        },
        {
            "symbol": "CAT",
            "date": "2024-10-21",
            "recordDate": "2024-10-21",
            "paymentDate": "2024-11-20",
            "declarationDate": "2024-10-09",
            "adjDividend": 1.41,
            "dividend": 1.41,
            "yield": 1.4,
            "frequency": "Quarterly",
        },
    ]
    urls = []

    def opener(url, timeout):
        urls.append(url)
        return io.BytesIO(json.dumps(payload).encode())

    from types import SimpleNamespace

    monkeypatch.setattr(
        openbb_client,
        "obb",
        SimpleNamespace(user=SimpleNamespace(credentials=SimpleNamespace(fmp_api_key="k"))),
    )

    frame = openbb_client._fmp_rest_dividends("CAT", "2025-01-01", opener=opener)

    assert "symbol=CAT" in urls[0]
    assert list(frame.ex_dividend_date) == ["2026-10-26"], "2024 is outside the window"
    assert frame.loc[0, "amount"] == 1.63 and frame.loc[0, "adjusted_amount"] == 1.63
    assert frame.loc[0, "payment_date"] is None, "a blank date is missing, not an error"
    assert frame.loc[0, "record_date"] == "2026-10-26"


def _credentials():
    from pydantic import BaseModel

    class Credentials(BaseModel):
        fmp_api_key: str | None = None
        fred_api_key: str | None = None

    return Credentials()


def test_credentials_file_sets_only_keys_openbb_defines(tmp_path, monkeypatch):
    monkeypatch.setattr(openbb_client, "_direct_keys", {})
    path = tmp_path / "creds.json"
    path.write_text(
        '{"credentials": {"FMP_API_KEY": " abc ", "fred_api_key": "",'
        ' "reddit_client_secret": "nope", "polygon_api_key": " poly "}}'
    )
    target = _credentials()

    applied = openbb_client.load_credentials(path, target)

    assert applied == ["fmp_api_key"]
    assert target.fmp_api_key == "abc"
    assert target.fred_api_key is None
    assert openbb_client._direct_keys == {"polygon_api_key": "poly"}, "kept for direct calls"


def test_a_missing_or_broken_credentials_file_is_harmless(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")

    assert openbb_client.load_credentials(tmp_path / "absent.json", _credentials()) == []
    assert openbb_client.load_credentials(broken, _credentials()) == []


def _fmp_tree(answers=None):
    """Patch obb with the statement/filings commands; answers maps command -> frame/error."""
    from types import SimpleNamespace

    answers = answers or {}
    calls = []

    def make(name):
        def call(**kwargs):
            calls.append((name, kwargs))
            answer = answers.get(name)
            if isinstance(answer, Exception):
                raise answer
            return _Response(answer)

        return call

    fake = SimpleNamespace(
        equity=SimpleNamespace(
            fundamental=SimpleNamespace(
                income=make("income"),
                balance=make("balance"),
                cash=make("cash"),
                filings=make("filings"),
            )
        ),
        user=SimpleNamespace(credentials=SimpleNamespace(fmp_api_key="k")),
    )
    return fake, calls


def test_financial_statements_use_the_fmp_provider(monkeypatch):
    fake, calls = _fmp_tree({"income": EVENTS})
    monkeypatch.setattr(openbb_client, "obb", fake)
    monkeypatch.setattr(openbb_client.settings, "openbb_provider", None)

    frame = openbb_client.financial_statements("KO", statement="income", limit=3)

    assert calls == [("income", {"symbol": "KO", "provider": "fmp", "limit": 3})]
    assert not frame.empty


def test_financial_statements_reject_an_unknown_type():
    with pytest.raises(ValueError, match="unknown FMP statement"):
        openbb_client.financial_statements("KO", statement="cashflow")


def test_filings_use_the_fmp_provider(monkeypatch):
    fake, calls = _fmp_tree({"filings": EVENTS})
    monkeypatch.setattr(openbb_client, "obb", fake)
    monkeypatch.setattr(openbb_client.settings, "openbb_provider", None)

    openbb_client.filings("KO", limit=5)

    assert calls == [("filings", {"symbol": "KO", "provider": "fmp", "limit": 5})]


def test_discounted_cash_flow_reads_fmp_directly(monkeypatch):
    import io
    import json
    from datetime import date

    monkeypatch.setattr(openbb_client, "_fmp_key", lambda: "k")
    monkeypatch.setattr(openbb_client, "_fmp_calls", openbb_client.deque())
    urls = []

    def opener(url, timeout):
        urls.append(url)
        return io.BytesIO(
            json.dumps(
                [{"symbol": "AAPL", "date": "2026-10-20", "dcf": 135.6, "Stock Price": 340.7}]
            ).encode()
        )

    result = openbb_client.discounted_cash_flow("AAPL", opener=opener)

    assert result == {
        "as_of_date": date(2026, 10, 20),
        "dcf": 135.6,
        "stock_price": 340.7,
        "reported_currency": None,
    }
    assert "symbol=AAPL" in urls[0] and "apikey=k" in urls[0]


def test_discounted_cash_flow_without_a_key_returns_none(monkeypatch):
    monkeypatch.setattr(openbb_client, "_fmp_key", lambda: None)
    assert openbb_client.discounted_cash_flow("AAPL") is None


def test_discounted_cash_flow_a_non_429_error_returns_none(monkeypatch):
    import io
    from urllib.error import HTTPError

    monkeypatch.setattr(openbb_client, "_fmp_key", lambda: "k")
    monkeypatch.setattr(openbb_client, "_fmp_calls", openbb_client.deque())

    def opener(url, timeout):
        raise HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))

    assert openbb_client.discounted_cash_flow("AAPL", opener=opener) is None
