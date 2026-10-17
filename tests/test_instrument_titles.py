"""pick_best_filing must choose the most recent filing in the preferred form tier.

Regression: a single ascending sort on (form_priority, filing_date) returned
the OLDEST annual report, so dei cover titles were parsed from decade-old
instances (or none at all when that old report predates XBRL).
"""

from scripts import populate_sec_instrument_titles as ingest
from scripts.populate_sec_instrument_titles import pick_best_filing
from src.crispdm.sec_client import parse_dei_instrument_titles


def _context_instance(facts):
    return (
        '<xbrl xmlns:dei="http://xbrl.sec.gov/dei/2025">'
        '<context id="a"><period><instant>2026-01-01</instant></period></context>'
        '<context id="b"><period><instant>2026-01-01</instant></period></context>'
        '<context id="old"><period><instant>2025-01-01</instant></period></context>'
        + "".join(
            f'<dei:{tag} contextRef="{context}">{value}</dei:{tag}>'
            for context, tag, value in facts
        )
        + "</xbrl>"
    )


def test_context_binding_keeps_identical_titles_for_distinct_classes():
    title = "Depositary Shares, each representing 1/1000 of a share"
    xml = _context_instance(
        [
            ("a", "Security12bTitle", title),
            ("a", "TradingSymbol", "BAC PrB"),
            ("b", "Security12bTitle", title),
            ("b", "TradingSymbol", "BAC PrE"),
        ]
    )
    assert parse_dei_instrument_titles(xml)[0] == [("BAC PRB", title), ("BAC PRE", title)]


def test_context_binding_ignores_unpaired_rights_title():
    xml = _context_instance(
        [
            ("a", "Security12bTitle", "Preferred Stock, Series D"),
            ("a", "TradingSymbol", "AHT-PD"),
            ("b", "Security12bTitle", "Preferred Stock Repurchase Rights"),
        ]
    )
    assert parse_dei_instrument_titles(xml)[0] == [("AHT-PD", "Preferred Stock, Series D")]


def test_context_binding_does_not_zip_reordered_fact_lists():
    xml = _context_instance(
        [
            ("a", "TradingSymbol", "ABC-PA"),
            ("b", "TradingSymbol", "ABC-PB"),
            ("b", "Security12bTitle", "Series B Preferred Stock"),
            ("a", "Security12bTitle", "Series A Preferred Stock"),
        ]
    )
    assert parse_dei_instrument_titles(xml)[0] == [
        ("ABC-PA", "Series A Preferred Stock"),
        ("ABC-PB", "Series B Preferred Stock"),
    ]


def test_context_binding_keeps_newest_title_per_symbol():
    xml = _context_instance(
        [
            ("a", "TradingSymbol", "ABC-PA"),
            ("a", "Security12bTitle", "New Series A Preferred Stock"),
            ("old", "TradingSymbol", "ABC-PA"),
            ("old", "Security12bTitle", "Old Series A Preferred Stock"),
        ]
    )
    assert parse_dei_instrument_titles(xml)[0] == [("ABC-PA", "New Series A Preferred Stock")]


def test_canonical_title_symbol_maps_only_unique_issuer_spellings():
    title = "Depositary Shares, each representing 1/1000 of a preferred share"
    assert ingest.canonical_title_symbol("FRT-C", title, ["FRT", "FRT-PC"]) == "FRT-PC"
    assert ingest.canonical_title_symbol("STT.PRG", title, ["STT", "STT-PG"]) == "STT-PG"
    assert ingest.canonical_title_symbol("KRGPI", title, ["KRG", "KRG-PI"]) == "KRG-PI"
    assert ingest.canonical_title_symbol("ADCPRA", title, ["ADC", "ADC-PA"]) == "ADC-PA"
    assert ingest.canonical_title_symbol("ALB PR A", title, ["ALB", "ALB-PA"]) == "ALB-PA"
    assert ingest.canonical_title_symbol("ALL.PR.B", title, ["ALL", "ALL-PB"]) == "ALL-PB"
    assert ingest.canonical_title_symbol("ASB PRE", title, ["ASB", "ASB-PE"]) == "ASB-PE"
    assert ingest.canonical_title_symbol("BFS/PRD", title, ["BFS", "BFS-PD"]) == "BFS-PD"
    assert (
        ingest.canonical_title_symbol(
            "ALL.PR.B", "Subordinated Debentures due 2053", ["ALL", "ALL-PB"]
        )
        == "ALL-PB"
    )
    assert ingest.canonical_title_symbol("FRT-C", title, ["OTHER-PC"]) == "FRT-C"


def test_canonical_title_symbol_preserves_common_and_ambiguous_symbols():
    assert ingest.canonical_title_symbol("ABC-A", "Class A common stock", ["ABC-PA"]) == "ABC-A"
    assert ingest.canonical_title_symbol("ABC-A", "Preferred Stock", ["ABC-A", "ABC-PA"]) == "ABC-A"
    assert ingest.canonical_title_symbol("ABCA", "Preferred Stock", ["ABC-A", "ABC.A"]) == "ABCA"


def test_preferred_universe_filter():
    conn = _FakeConnection()
    ingest.load_cik_universe(conn, preferred_only=True)
    assert "s.security_type = 'preferred stock'" in conn.statements[0]


def test_known_symbols_prefer_canonical_reference_not_filed_aliases():
    class Conn:
        def execute(self, statement, params):
            assert "reference.securities" in str(statement)
            assert params == {"cik": "0000007789"}
            return self

        def scalars(self):
            return iter(["ASB", "ASB-PE"])

    assert ingest.get_submission_symbols(Conn(), "0000007789") == ["ASB", "ASB-PE"]


def test_offline_ingest_returns_stage_result_tuple(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    monkeypatch.setattr(ingest, "OFFLINE_ON", True)
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(scalar=lambda: 9))
    monkeypatch.setattr(ingest, "engine", SimpleNamespace(connect=lambda: nullcontext(conn)))
    assert ingest.populate_sec_instrument_titles() == (0, 0, 0, 0)


def _preferred_row(**overrides):
    row = {
        "security_id": "sid",
        "ticker": "FRT-PC",
        "security_name": "Issuer",
        "coupon_rate": None,
        "liquidation_preference": None,
        "title": "5% Series C Preferred Stock, liquidation preference $25",
        "provider": "SEC_XBRL",
        "profile_coupon": None,
        "profile_coupon_type": None,
        "profile_preference": None,
    }
    row.update(overrides)
    return row


def test_apply_exact_titles_fills_missing_terms_and_records_profile_history(monkeypatch):
    profiles = []
    monkeypatch.setattr(
        ingest, "upsert_ticker_profile", lambda conn, row, **kw: profiles.append((row, kw))
    )
    conn = _FakeConnection([_preferred_row()])
    assert ingest.apply_preferred_titles(conn, ["0000034903"]) == 1
    assert profiles[0][0]["coupon_rate"] == 5
    assert profiles[0][0]["liquidation_preference"] == 25
    assert profiles[0][1]["refreshed"] is False
    assert "t.cik = s.cik AND t.ticker = s.ticker" in conn.statements[0]


def test_apply_titles_does_not_replace_existing_terms(monkeypatch):
    profiles = []
    monkeypatch.setattr(ingest, "upsert_ticker_profile", lambda *args, **kw: profiles.append(args))
    row = _preferred_row(
        security_name="5% Series C Preferred Stock, liquidation preference $25",
        coupon_rate=7,
        liquidation_preference=50,
        profile_coupon=7,
        profile_coupon_type="floating",
        profile_preference=50,
    )
    conn = _FakeConnection([row])
    assert ingest.apply_preferred_titles(conn, ["0000034903"]) == 0
    assert len(conn.statements) == 1
    assert profiles == []


def test_apply_titles_leaves_depositary_units_to_contract_miner(monkeypatch):
    profiles = []
    monkeypatch.setattr(
        ingest, "upsert_ticker_profile", lambda conn, row, **kw: profiles.append(row)
    )
    row = _preferred_row(
        title="5% Depositary Shares each representing 1/1000 of Series C Preferred Stock, liquidation preference $25,000"
    )
    assert ingest.apply_preferred_titles(_FakeConnection([row]), ["0000034903"]) == 1
    assert profiles[0]["coupon_rate"] == 5
    assert "liquidation_preference" not in profiles[0]


def test_apply_titles_rejects_common_title_for_preferred(monkeypatch):
    def unexpected_profile(*args, **kwargs):
        raise AssertionError("A common-stock title must not populate preferred terms")

    monkeypatch.setattr(ingest, "upsert_ticker_profile", unexpected_profile)
    conn = _FakeConnection([_preferred_row(title="Class A common stock")])
    assert ingest.apply_preferred_titles(conn, ["0000034903"]) == 0
    assert len(conn.statements) == 1


def test_apply_titles_does_not_treat_floating_spread_as_coupon(monkeypatch):
    profiles = []
    monkeypatch.setattr(ingest, "upsert_ticker_profile", lambda *a, **kw: profiles.append(a))
    conn = _FakeConnection(
        [_preferred_row(title="Series A Floating Rate Preferred Stock, SOFR + 3.5%")]
    )
    assert ingest.apply_preferred_titles(conn, ["0000034903"]) == 1
    assert profiles == []


def test_resume_checks_current_accession_and_missing_active_preferred_titles():
    class Conn:
        def execute(self, statement, params):
            self.sql = str(statement)
            self.params = params
            return self

        def scalar(self):
            return False

    conn = Conn()
    assert not ingest.titles_stored_for_cik(conn, "0000034903", "new-accession")
    assert conn.params["accession"] == "new-accession"
    assert "s.active" in conn.sql
    assert "t.ticker = s.ticker" in conn.sql
    assert "t.accession_no = :accession" in conn.sql


def _payload(accessions_forms_dates):
    rows = [
        {
            "accessionNumber": [a],
            "form": [f],
            "filingDate": [d],
            "isXBRL": [True],
            "primaryDocument": [f"{a}.htm"],
        }
        for a, f, d in accessions_forms_dates
    ]
    return _merge(rows)


def _merge(rows):
    keys = ("accessionNumber", "form", "filingDate", "isXBRL", "primaryDocument")
    out = {key: [row[key][0] for row in rows] for key in keys}
    return {"filings": {"recent": out}}


def test_prefers_most_recent_annual_report():
    payload = _payload(
        [
            ("0001294154-12-000054", "10-K", "2012-03-30"),
            ("0001193125-18-100000", "10-K", "2018-03-15"),
            ("0001104659-20-040000", "10-K", "2020-02-27"),
        ]
    )
    pick = pick_best_filing(payload)
    assert pick["accession"] == "0001104659-20-040000"
    assert pick["filing_date"] == "2020-02-27"


def test_prefers_annual_report_over_nearer_quarterly():
    payload = _payload(
        [
            ("0001193125-18-100000", "10-K", "2018-03-15"),
            ("0001104659-23-070000", "10-Q", "2023-11-06"),
        ]
    )
    pick = pick_best_filing(payload)
    assert pick["form"] == "10-K"
    assert pick["accession"] == "0001193125-18-100000"


def test_skips_non_xbrl_filings():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001294154-12-000054"],
                "form": ["8-K"],
                "filingDate": ["2024-01-01"],
                "isXBRL": [False],
                "primaryDocument": ["filing.htm"],
            }
        }
    }
    assert pick_best_filing(payload) is None


def test_empty_payload_returns_none():
    assert pick_best_filing({}) is None
    assert pick_best_filing(None) is None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result(self._rows)


def test_load_cik_universe_defaults_to_active_securities():
    from scripts.populate_sec_instrument_titles import load_cik_universe

    conn = _FakeConnection([{"cik": "0000320193"}])

    ciks = load_cik_universe(conn)

    assert ciks == ["0000320193"]
    assert "s.active = TRUE" in conn.statements[0]


def test_load_cik_universe_keeps_active_filter_with_explicit_cik():
    from scripts.populate_sec_instrument_titles import load_cik_universe

    conn = _FakeConnection()

    load_cik_universe(conn, cik="320193")

    assert "s.active = TRUE" in conn.statements[0]
    assert "s.cik = :cik" in conn.statements[0]
