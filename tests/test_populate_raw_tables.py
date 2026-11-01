import json
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
        patch.object(prt, "observed_payer_keys", return_value=set()),
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
        patch.object(prt, "observed_payer_keys", return_value=set()),
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
        patch.object(prt, "observed_payer_keys", return_value=set()),
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
        self.profile_sql = []
        self.load_rows = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO raw.ticker_profile AS current_profile" in sql:
            self.profile_rows.append(params)
            self.profile_sql.append(sql)
        elif "INSERT INTO raw.ticker_profile_load" in sql:
            self.load_rows.append(params)
        return _Rows([])

    def commit(self):
        pass


def _run_profile_stage(conn, parsed_coupon, sec_coupon, sec_liquidation=None, openbb="{}"):
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
            return_value={
                "coupon_rate": sec_coupon,
                "liquidation_preference": sec_liquidation,
            },
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
                "raw_payload": openbb,
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


def test_sec_xbrl_terms_never_fill_the_per_series_columns():
    """Issuer-level SEC facts are evidence, not a per-series fallback.

    They carry no series dimension and fall back to par value, so stamping
    them into coupon_rate/liquidation_preference put common-stock par values
    (0.01, 0.0001) onto thousands of securities.
    """
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=None, sec_coupon=6.50, sec_liquidation=0.01)

    row = conn.profile_rows[0]
    assert row["coupon_rate"] is None
    assert row["liquidation_preference"] is None
    payload = json.loads(row["raw_payload"])
    assert payload["sec_xbrl"] == {"coupon_rate": 6.50, "liquidation_preference": 0.01}
    assert payload["sec_xbrl_scope"] == "issuer_level_unallocated"


def test_every_profile_write_is_appended_to_the_load_history_first():
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=7.25, sec_coupon=None)

    assert len(conn.load_rows) == 1
    assert conn.load_rows[0]["loader"] == "populate_raw_tables"
    assert conn.load_rows[0]["payload_hash"]


def test_name_parse_columns_are_owned_and_overwritten_not_coalesced():
    conn = _ProfileConn()

    _run_profile_stage(conn, parsed_coupon=None, sec_coupon=None)

    sql = conn.profile_sql[0]
    assert "coupon_rate = EXCLUDED.coupon_rate" in sql
    assert "liquidation_preference = EXCLUDED.liquidation_preference" in sql
    assert "COALESCE(EXCLUDED.coupon_rate" not in sql
    # OpenBB returned nothing, so sector/industry are not owned and are kept.
    assert "sector = EXCLUDED.sector" not in sql
    assert "openbb" not in json.loads(conn.profile_rows[0]["raw_payload"])
    assert conn.profile_rows[0]["provider"] == "SEC_XBRL"


def test_openbb_columns_are_owned_when_openbb_answered():
    conn = _ProfileConn()

    _run_profile_stage(
        conn, parsed_coupon=None, sec_coupon=None, openbb='{"symbol": "AAA", "sector": "Energy"}'
    )

    assert "sector = EXCLUDED.sector" in conn.profile_sql[0]
    payload = json.loads(conn.profile_rows[0]["raw_payload"])
    assert payload["openbb"] == {"symbol": "AAA", "sector": "Energy"}
    assert set(payload) <= {"openbb", "sec_xbrl", "sec_xbrl_scope"}
    assert conn.profile_rows[0]["provider"] == "SEC_XBRL+OPENBB_YFINANCE"


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


# --- ticker / CIK conflict guard -------------------------------------------------
#
# SEC reassigned PORT-UN to Southport Acquisition Corp. II while reference.securities
# still pointed at Angel Studios. fk_securities_company_ticker made the upsert raise,
# the whole company_ticker transaction rolled back, and the nightly stopped before
# build_features. The guard must contain exactly that conflict and nothing else.

ANGEL = {
    "ticker": "PORT-UN",
    "cik": "0001865200",
    "title": "Angel Studios, Inc.",
    "securities": 1,
}


def _southport(ticker):
    return {"ticker": ticker, "cik_str": 2148436, "title": "Southport Acquisition Corp. II"}


class _MappingRows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)


class _TickerConn:
    """Serves the referenced-owner lookup and records every write.

    ``owners`` are the raw.company_ticker rows a reference.securities row still
    points at. ``fail_on`` makes the upsert for one ticker raise, standing in for a
    real database or source failure that the guard must not swallow.
    """

    def __init__(self, owners=(), fail_on=None):
        self.owners = list(owners)
        self.fail_on = fail_on
        self.upserts = []
        self.statements = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "JOIN reference.securities s ON s.ticker" in sql:
            return _MappingRows(self.owners)
        if "INSERT INTO raw.company_ticker" in sql:
            if params["ticker"] == self.fail_on:
                raise RuntimeError("database unavailable")
            self.upserts.append(params)
        return _MappingRows([])


def test_a_new_ticker_is_inserted():
    conn = _TickerConn()

    result = prt._refresh_company_tickers(conn, [_southport("PORT")])

    assert [u["ticker"] for u in conn.upserts] == ["PORT"]
    assert (result.seen, result.ingested, result.conflicts) == (1, 1, [])


def test_the_same_cik_is_processed_idempotently():
    owner = {
        "ticker": "PORT",
        "cik": "0002148436",
        "title": "Southport Acquisition Corp. II",
        "securities": 1,
    }
    conn = _TickerConn([owner])

    first = prt._refresh_company_tickers(conn, [_southport("PORT")])
    second = prt._refresh_company_tickers(conn, [_southport("PORT")])

    assert first.conflicts == [] and second.conflicts == []
    assert len(conn.upserts) == 2, "an unchanged ticker must still be refreshed normally"


def test_a_different_cik_is_skipped_reported_and_never_written():
    conn = _TickerConn([ANGEL])

    result = prt._refresh_company_tickers(conn, [_southport("PORT-UN")])

    assert conn.upserts == [], "the conflicting ticker must not be upserted"
    assert result.ingested == 0 and result.seen == 1
    (conflict,) = result.conflicts
    assert conflict == {
        "conflict_type": "TICKER_CIK_CONFLICT",
        "ticker": "PORT-UN",
        "incoming_cik": "0002148436",
        "incoming_issuer": "Southport Acquisition Corp. II",
        "existing_cik": "0001865200",
        "existing_issuer": "Angel Studios, Inc.",
        "referencing_securities": 1,
        "action": "SKIPPED",
        "resolution": "MANUAL_REVIEW_REQUIRED",
    }
    # Containment, not entity resolution: nothing existing was updated, deleted or re-keyed.
    mutations = [
        s
        for s in conn.statements
        if "INSERT INTO raw.company_ticker" in s
        or "UPDATE reference.securities" in s
        or "DELETE FROM" in s
        or "UPDATE raw.company_ticker" in s
    ]
    assert mutations == []


def test_southport_regression_one_conflicting_ticker_does_not_block_the_issuer():
    """PORT and PORT.U ingest; PORT-UN is skipped; nothing is lost or re-keyed."""
    conn = _TickerConn([ANGEL])

    result = prt._refresh_company_tickers(
        conn, [_southport("PORT"), _southport("PORT.U"), _southport("PORT-UN")]
    )

    assert [u["ticker"] for u in conn.upserts] == ["PORT", "PORT.U"]
    assert (result.seen, result.ingested) == (3, 2)
    assert [c["ticker"] for c in result.conflicts] == ["PORT-UN"]


def test_every_conflict_is_recorded_independently_and_the_run_continues():
    other = {"ticker": "ZZZ", "cik": "0000000009", "title": "Old ZZZ", "securities": 2}
    conn = _TickerConn([ANGEL, other])
    entries = [
        _southport("PORT-UN"),
        {"ticker": "ZZZ", "cik_str": 77, "title": "New ZZZ"},
        _southport("PORT"),
    ]

    result = prt._refresh_company_tickers(conn, entries)

    assert sorted(c["ticker"] for c in result.conflicts) == ["PORT-UN", "ZZZ"]
    assert next(c for c in result.conflicts if c["ticker"] == "ZZZ")["referencing_securities"] == 2
    assert [u["ticker"] for u in conn.upserts] == ["PORT"], (
        "the valid ticker after them is processed"
    )


def test_a_repeated_snapshot_entry_is_reported_once():
    conn = _TickerConn([ANGEL])

    result = prt._refresh_company_tickers(conn, [_southport("PORT-UN"), _southport("PORT-UN")])

    assert len(result.conflicts) == 1


def test_the_ticker_is_normalised_before_it_is_compared():
    """A casing or whitespace variant must not slip past the guard and re-trigger the FK."""
    conn = _TickerConn([ANGEL])

    result = prt._refresh_company_tickers(conn, [_southport("  port-un ")])

    assert conn.upserts == []
    assert result.conflicts[0]["ticker"] == "PORT-UN"


def test_a_cik_that_only_differs_by_padding_is_not_a_conflict():
    owner = {"ticker": "PORT", "cik": "0002148436", "title": "Southport", "securities": 1}
    conn = _TickerConn([owner])

    result = prt._refresh_company_tickers(
        conn, [{"ticker": "PORT", "cik_str": "2148436", "title": "Southport"}]
    )

    assert result.conflicts == [] and len(conn.upserts) == 1


def test_a_ticker_no_security_references_is_still_refreshed():
    """The guard is for the integrity conflict only: an unreferenced row is free to change."""
    conn = _TickerConn([ANGEL])  # only PORT-UN is referenced

    result = prt._refresh_company_tickers(conn, [_southport("NEWCO")])

    assert [u["ticker"] for u in conn.upserts] == ["NEWCO"] and result.conflicts == []


def test_a_real_failure_after_a_conflict_is_still_a_failure():
    conn = _TickerConn([ANGEL], fail_on="PORT")

    try:
        prt._refresh_company_tickers(conn, [_southport("PORT-UN"), _southport("PORT")])
    except RuntimeError as exc:
        assert "database unavailable" in str(exc)
    else:
        raise AssertionError("a genuine write failure was swallowed by the conflict guard")


def test_a_remediated_conflict_ingests_on_rerun_with_no_override():
    """The fix is to the data, not the pipeline: same entries, same code path."""
    entries = [_southport("PORT-UN")]

    before = _TickerConn([ANGEL])
    blocked = prt._refresh_company_tickers(before, entries)
    after = _TickerConn([])  # the stale Angel Studios reference has since been remediated
    cleared = prt._refresh_company_tickers(after, entries)

    assert blocked.ingested == 0 and len(blocked.conflicts) == 1
    assert cleared.ingested == 1 and cleared.conflicts == []
    assert [u["ticker"] for u in after.upserts] == ["PORT-UN"]


def test_the_nightly_no_longer_resets_the_foreign_key_to_not_valid():
    """Dropping and re-adding fk_securities_company_ticker always yields NOT VALID.

    Every nightly therefore undid V0046's validation, so the live schema drifted
    from the repository one run after each fix.
    """
    import inspect

    source = inspect.getsource(prt._refresh_company_tickers)

    assert "DROP CONSTRAINT IF EXISTS fk_securities_company_ticker" not in source
    assert "IF NOT EXISTS" in source and "ADD CONSTRAINT fk_securities_company_ticker" in source


def _run_main(monkeypatch, refresh):
    import sys

    monkeypatch.setattr(sys, "argv", ["populate_raw_tables", "--skip-profiles"])
    monkeypatch.setattr(prt, "populate_company_tickers", lambda limit=None: refresh)
    return prt.main()


def test_the_stage_completes_with_a_warning_when_some_tickers_conflict(monkeypatch, capsys):
    conflict = {
        "conflict_type": "TICKER_CIK_CONFLICT",
        "ticker": "PORT-UN",
        "incoming_cik": "0002148436",
        "incoming_issuer": "Southport Acquisition Corp. II",
        "existing_cik": "0001865200",
        "existing_issuer": "Angel Studios, Inc.",
        "referencing_securities": 1,
        "action": "SKIPPED",
        "resolution": "MANUAL_REVIEW_REQUIRED",
    }

    code = _run_main(monkeypatch, prt.TickerRefresh(seen=3, ingested=2, conflicts=[conflict]))

    out = capsys.readouterr()
    assert code == 0
    assert "completed with warnings (1 ticker/CIK conflict(s) skipped)" in out.out
    assert "[ticker_cik_conflict]" in out.err and '"ticker": "PORT-UN"' in out.err
    assert "No existing ticker mapping was modified" in out.err
    assert "PORT-UN: incoming Southport Acquisition Corp. II" in out.err


def test_a_clean_run_prints_no_warning(monkeypatch, capsys):
    code = _run_main(monkeypatch, prt.TickerRefresh(seen=3, ingested=3, conflicts=[]))

    out = capsys.readouterr()
    assert code == 0
    assert "populated successfully" in out.out and out.err == ""


def test_a_run_in_which_every_ticker_conflicted_still_fails(monkeypatch):
    """Conflicts are not 'skipped' work: wrote nothing is a failure, as for any stage."""
    conflict = {
        "ticker": "A",
        "incoming_issuer": "x",
        "incoming_cik": "1",
        "existing_issuer": "y",
        "existing_cik": "2",
    }

    code = _run_main(monkeypatch, prt.TickerRefresh(seen=1, ingested=0, conflicts=[conflict]))

    assert code == 1


# --- the registry record of a skipped conflict ------------------------------------

_PORT_CONFLICT = {
    "conflict_type": "TICKER_CIK_CONFLICT",
    "ticker": "PORT-UN",
    "incoming_cik": "0002148436",
    "incoming_issuer": "Southport Acquisition Corp. II",
    "existing_cik": "0001865200",
    "existing_issuer": "Angel Studios, Inc.",
    "referencing_securities": 1,
}


class _RegistryConn:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def begin_nested(self):
        import contextlib

        return contextlib.nullcontext()

    def execute(self, stmt, params=None):
        if self.error:
            raise self.error
        self.calls.append((str(stmt), params))


def test_a_skipped_conflict_is_written_to_the_registry_with_both_ciks():
    conn = _RegistryConn()

    prt.record_ticker_conflicts(conn, [_PORT_CONFLICT], sweep=False)

    ((sql, params),) = conn.calls
    assert "INSERT INTO audit.quarantined_values" in sql
    assert params["ticker"] == "PORT-UN"
    assert (params["existing_cik"], params["incoming_cik"]) == ("0001865200", "0002148436")
    assert params["rule"] == "TICKER_CIK_CONFLICT"
    assert "Angel Studios" in params["reason"] and "Southport" in params["reason"]


def test_an_open_row_is_left_alone_and_only_a_resolved_one_is_reopened():
    conn = _RegistryConn()
    prt.record_ticker_conflicts(conn, [_PORT_CONFLICT], sweep=False)
    sql = conn.calls[0][0]
    assert "DO UPDATE" in sql and "WHERE audit.quarantined_values.resolved_at IS NOT NULL" in sql


def test_a_long_ticker_keeps_its_full_form_as_the_row_key():
    conflict = dict(_PORT_CONFLICT, ticker="ABCDEFGHIJKLMNOPQRS-WT")
    conn = _RegistryConn()

    prt.record_ticker_conflicts(conn, [conflict], sweep=False)

    params = conn.calls[0][1]
    assert params["ticker"] == "ABCDEFGHIJKLMNOPQRS-WT" and len(params["short"]) == 16


def test_a_full_snapshot_resolves_conflicts_sec_no_longer_reports():
    conn = _RegistryConn()

    prt.record_ticker_conflicts(conn, [_PORT_CONFLICT], sweep=True)

    sql, params = conn.calls[-1]
    assert sql.lstrip().startswith("UPDATE audit.quarantined_values")
    assert "table_schema = 'raw'" in sql, "released (reference) rows are not this run's to close"
    assert params["still_open"] == ["PORT-UN|0002148436"]


def test_a_clean_full_snapshot_resolves_every_open_conflict():
    conn = _RegistryConn()
    prt.record_ticker_conflicts(conn, [], sweep=True)
    assert conn.calls[-1][1]["still_open"] == []


def test_a_partial_snapshot_never_resolves_anything():
    """--limit and the offline re-read see a subset, so absence proves nothing."""
    conn = _RegistryConn()

    prt.record_ticker_conflicts(conn, [], sweep=False)
    prt.record_ticker_conflicts(conn, [_PORT_CONFLICT], sweep=False)

    assert not any("UPDATE audit.quarantined_values" in sql for sql, _ in conn.calls)


def test_a_registry_failure_is_reported_and_does_not_fail_the_stage(capsys):
    from sqlalchemy.exc import SQLAlchemyError

    conn = _RegistryConn(error=SQLAlchemyError("relation does not exist"))

    prt.record_ticker_conflicts(conn, [_PORT_CONFLICT], sweep=True)

    assert "could not record ticker conflicts" in capsys.readouterr().err


def test_only_a_full_online_refresh_may_resolve_conflicts(monkeypatch):
    seen = []
    refresh = prt.TickerRefresh(seen=1, ingested=1, conflicts=[])

    class _Begin:
        def __enter__(self):
            return "conn"

        def __exit__(self, *exc):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    monkeypatch.setattr(prt, "OFFLINE_ON", False)
    monkeypatch.setattr(prt, "engine", _Engine())
    monkeypatch.setattr(prt, "get_company_tickers", lambda: {"a": {"ticker": "A", "cik_str": 1}})
    monkeypatch.setattr(prt, "_refresh_company_tickers", lambda conn, entries: refresh)
    monkeypatch.setattr(
        prt, "record_ticker_conflicts", lambda conn, conflicts, *, sweep: seen.append(sweep)
    )

    prt.populate_company_tickers()
    prt.populate_company_tickers(limit=5)

    assert seen == [True, False]


def test_reference_terms_update_leaves_common_stock_alone_but_still_updates_preferreds():
    """The real statement against Postgres, in a transaction that is always rolled back.

    A common-stock row must not receive preferred coupon/liquidation terms (that is the
    leak the nightly verification fails on), while a preferred row must still be updated:
    the guard must not block legitimate writes.
    """
    import pytest
    from sqlalchemy import text

    try:
        from scripts.populate_raw_tables import REFERENCE_TERMS_UPDATE
        from src.crispdm.db import engine

        conn = engine.connect()
        conn.exec_driver_sql("SELECT 1")
        conn.rollback()
    except Exception:  # pragma: no cover - environments without a database
        pytest.skip("no database available")
    trans = conn.begin()
    try:
        picks = {}
        for kind in ("common_stock", "preferred stock"):
            row = conn.execute(
                text(
                    "SELECT security_id FROM reference.securities WHERE active "
                    "AND security_type = :t AND coupon_rate IS NULL "
                    "AND liquidation_preference IS NULL LIMIT 1"
                ),
                {"t": kind},
            ).scalar()
            if row is None:
                pytest.skip(f"no active {kind} row without terms to test against")
            picks[kind] = row
        for kind, security_id in picks.items():
            conn.execute(
                REFERENCE_TERMS_UPDATE,
                {
                    "security_id": security_id,
                    "coupon_rate": 6.25,
                    "liquidation_preference": 25.0,
                    "call_date": None,
                },
            )
        got = {
            kind: conn.execute(
                text(
                    "SELECT coupon_rate, liquidation_preference FROM reference.securities "
                    "WHERE security_id = :s"
                ),
                {"s": security_id},
            ).one()
            for kind, security_id in picks.items()
        }
        assert got["common_stock"].coupon_rate is None
        assert got["common_stock"].liquidation_preference is None
        assert float(got["preferred stock"].coupon_rate) == 6.25
        assert float(got["preferred stock"].liquidation_preference) == 25.0
    finally:
        trans.rollback()
        conn.close()
