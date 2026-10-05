from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts import populate_raw_tables as prt

_CLASSIFICATION = {
    "security_types": ["common stock"],
    "dividend": True,
    "security_titles": ["Acme"],
    "security_facts": [],
    "dividend_facts": [],
    "status": "ok",
}


class _ScaledConn:
    """Connection stand-in that serves companyfacts rows keyed by CIK."""

    def __init__(self, stored_rows):
        self.stored_rows = stored_rows
        self.commits = 0

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM raw.companyfacts" in sql and "raw_payload" in sql:
            return _Scalar(self.stored_rows.get((params or {}).get("cik")))
        if "raw.sec_instrument_titles" in sql:
            return _Rows([])
        return _Rows([])

    def commit(self):
        self.commits += 1


class _Rows:
    """Empty row set that supports the .mappings() chain the scan uses."""

    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return iter(self.rows)

    def scalar(self):
        return None


class _Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


def test_a_fresh_stored_payload_is_reused_instead_of_re_downloaded():
    """Stage 1 must not re-fetch a companyfacts payload that is already current.

    This scan reads every company ticker on every run and used to call
    ``get_companyfacts`` for each one unconditionally. Since ``upsert_companyfacts``
    re-stamps ``retrieved_at = now()``, a nightly that completed this stage
    re-downloaded all ~10,400 payloads and reset the freshness clock that stages
    4a-4c exist to maintain -- so a table could look current while the refresh
    stages had done nothing, and a genuinely stale CIK would be indistinguishable
    from one refreshed moments earlier.
    """
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    conn = _ScaledConn({"0000000001": {"entityName": "Acme"}})
    called = []
    upserted = []

    def _record_upsert(_conn, cik, _payload):
        upserted.append(cik)

    with (
        patch.object(prt, "stored_facts_retrieved_at", return_value={"0000000001": recent}),
        patch.object(prt, "engine") as eng,
        patch.object(
            prt,
            "classify_companyfacts",
            return_value=_CLASSIFICATION,
        ),
        patch.object(prt, "get_companyfacts", side_effect=lambda cik: called.append(cik)),
        patch.object(
            prt,
            "_load_raw_tickers",
            return_value=[{"cik": "0000000001", "ticker": "AAA", "title": "Acme"}],
        ),
        patch.object(prt, "upsert_companyfacts", side_effect=_record_upsert),
    ):
        eng.connect.return_value.__enter__.return_value = conn
        prt._identify_dividend_payers(reuse_max_age_days=5)

    assert called == [], "a payload 1 day old must be reused, not re-downloaded"
    # Reuse must also leave retrieved_at alone: the upsert is what re-stamps it,
    # and re-stamping is what made a stale table look current.
    assert not upserted, f"reuse must not upsert, got {upserted}"


def test_a_stale_stored_payload_is_re_fetched():
    """Reuse is bounded by age; an old payload must still be re-downloaded."""
    stale = datetime.now(timezone.utc) - timedelta(days=30)
    conn = _ScaledConn({"0000000001": {"entityName": "Acme"}})
    called = []

    with (
        patch.object(prt, "stored_facts_retrieved_at", return_value={"0000000001": stale}),
        patch.object(prt, "engine") as eng,
        patch.object(
            prt,
            "classify_companyfacts",
            return_value=_CLASSIFICATION,
        ),
        patch.object(prt, "build_companyfacts_concept_groups", return_value={}),
        patch.object(
            prt,
            "get_companyfacts",
            side_effect=lambda cik: called.append(cik) or {"entityName": "Acme"},
        ),
        patch.object(
            prt,
            "_load_raw_tickers",
            return_value=[{"cik": "0000000001", "ticker": "AAA", "title": "Acme"}],
        ),
        patch.object(prt, "upsert_companyfacts"),
        patch.object(prt, "_persist_classification_cache"),
    ):
        eng.connect.return_value.__enter__.return_value = conn
        prt._identify_dividend_payers(reuse_max_age_days=5)

    assert called == ["0000000001"], "a 30-day-old payload must be re-fetched"


def test_the_scan_commits_per_cik():
    """A long scan must not hold one transaction for all ~10,400 CIKs.

    With a single commit at the end, a timeout or a suspended host discarded the
    entire run; on this host a suspend is the expected case, not the pathological
    one. Per-CIK commits also make ``retrieved_at`` move as work completes, so the
    stage is observable while it runs.
    """
    conn = _ScaledConn({})
    rows = [{"cik": f"000000000{i}", "ticker": f"T{i}", "title": f"T{i}"} for i in range(3)]

    with (
        patch.object(prt, "stored_facts_retrieved_at", return_value={}),
        patch.object(prt, "engine") as eng,
        patch.object(prt, "get_companyfacts", return_value={"entityName": "X"}),
        patch.object(prt, "build_companyfacts_concept_groups", return_value={}),
        patch.object(
            prt,
            "classify_companyfacts",
            return_value=_CLASSIFICATION,
        ),
        patch.object(prt, "_load_raw_tickers", return_value=rows),
        patch.object(prt, "upsert_companyfacts"),
        patch.object(prt, "_persist_classification_cache"),
    ):
        eng.connect.return_value.__enter__.return_value = conn
        prt._identify_dividend_payers(reuse_max_age_days=5)

    assert conn.commits >= 3, f"expected a commit per CIK, got {conn.commits}"


class _ProfileConn:
    """Captures the raw.ticker_profile upsert so coupon precedence is assertable."""

    def __init__(self):
        self.profile_rows = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO raw.ticker_profile" in sql:
            self.profile_rows.append(params)
        return _Rows([])

    def commit(self):
        pass


def _run_profile_stage(conn, parsed_coupon, sec_coupon):
    payer = {
        "ticker": "AAA",
        "cik": "0000000001",
        "title": "Acme",
        "classification": _CLASSIFICATION,
        "security_types": ["common stock"],
        "security_titles": ["Acme"],
        "security_ids": {"common stock": "sec-1"},
    }

    with (
        patch.object(prt, "OFFLINE_ON", False),
        patch.object(prt, "engine") as eng,
        patch.object(prt, "_identify_dividend_payers", return_value=[payer]),
        patch.object(prt, "_upsert_minimal_securities"),
        patch.object(
            prt,
            "_stored_companyfacts",
            return_value={"full_facts": {"us-gaap": {}}},
        ),
        patch.object(
            prt,
            "extract_preferred_terms_from_companyfacts",
            return_value={"coupon_rate": sec_coupon, "liquidation_preference": None},
        ),
        patch.object(
            prt,
            "fetch_ticker_profile",
            return_value={
                "ticker": "AAA",
                "provider": "OPENBB_YFINANCE",
                "sector": None,
                "industry": None,
                "security_type": "common stock",
                "coupon_type": "fixed",
                "coupon_rate": parsed_coupon,
                "fixed_period_end": None,
                "floating_spread": None,
                "tax_status": None,
                "call_date": None,
                "liquidation_preference": None,
                "raw_payload": "{}",
            },
        ),
    ):
        eng.connect.return_value.__enter__.return_value = conn
        prt.populate_ticker_profiles()


def test_name_parsed_coupon_wins_over_sec_xbrl_terms():
    """A parsable per-security rate outranks the issuer-level SEC value.

    SEC Company Facts terms are read from the issuer's companyfacts, so they
    only describe a single-series issuer. Overwriting a good per-security parse
    with them mislabels every multi-series issuer.
    """
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=7.25, sec_coupon=6.50)

    assert conn.profile_rows[0]["coupon_rate"] == 7.25


def test_sec_xbrl_terms_are_the_fallback_when_the_title_does_not_parse():
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=None, sec_coupon=6.50)

    assert conn.profile_rows[0]["coupon_rate"] == 6.50


def test_no_coupon_is_stored_when_neither_source_has_a_rate():
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=None, sec_coupon=None)

    assert conn.profile_rows[0]["coupon_rate"] is None


def test_minimal_security_upsert_writes_last_paid_and_retires_flipped_twin():
    import uuid

    from scripts import populate_raw_tables as prt

    statements = []

    class _R:
        def first(self):
            return None

    class FakeConn:
        def execute(self, stmt, params=None):
            statements.append((str(stmt), params))
            return _R()

    sid = uuid.uuid4()
    payer = {
        "ticker": "BTLN",
        "cik": "0001854445",
        "title": "Brightline",
        "security_titles": [],
        "security_types": ["common_stock"],
        "security_ids": {"common_stock": sid},
        "classification": {
            "dividend": True,
            "status": "available",
            "dividend_last_paid": "2026-06-30",
        },
    }
    prt._upsert_minimal_securities(FakeConn(), payer)

    _lookup, insert, retire = statements
    assert insert[1]["dividend_last_paid"] == "2026-06-30"
    assert "dividend_last_paid" in insert[0]
    assert "SET active = FALSE" in retire[0]
    assert retire[1]["id"] == sid and retire[1]["dividend"] is True


def test_minimal_security_upsert_skips_when_legacy_row_holds_security_id():
    import uuid

    from scripts import populate_raw_tables as prt

    calls = []

    class FakeConn:
        def execute(self, stmt, params=None):
            calls.append(str(stmt))

            class R:
                def first(self):
                    return ("0001842566", "AISP", "preferred stock", False)

            return R()

    payer = {
        "ticker": "AISP",
        "cik": "0001842566",
        "title": "Airship",
        "security_titles": [],
        "security_types": ["preferred stock"],
        "security_ids": {"preferred stock": uuid.uuid4()},
        "classification": {"dividend": True, "status": "available"},
    }
    assert prt._upsert_minimal_securities(FakeConn(), payer) is False
    assert len(calls) == 1
