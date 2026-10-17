import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import populate_reference_tables


class _Result:
    def __init__(self, *, rows=None, scalar=None, first=None):
        self.rows = rows or []
        self.scalar_value = scalar
        self.first_value = first

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return self.rows

    def first(self):
        return self.first_value

    def scalar(self):
        return self.scalar_value


class _Connection:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return self.results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_stale_security_with_children_is_deactivated_and_retained():
    conn = _Connection(
        [
            _Result(
                rows=[
                    {
                        "security_id": "stale-security",
                        "security_type": "common_stock",
                        "dividend": False,
                    }
                ]
            ),
            _Result(scalar=True),
            _Result(),
        ]
    )
    log = {"deleted": 0, "cascaded": 0, "deactivated_with_children": []}

    populate_reference_tables._reconcile_instrument_rows(
        conn,
        "ABR-PD",
        "0001253986",
        "preferred stock",
        True,
        log,
    )

    assert log["deleted"] == 0
    assert log["deactivated_with_children"] == [("ABR-PD", "common_stock")]
    assert "SET active = FALSE" in conn.statements[2][0]


def test_contract_terms_is_a_security_child_and_a_reseed_cascade_target():
    """A reclassified primary keeps its old row but must not keep its terms row."""
    assert "preferred.contract_terms" in populate_reference_tables.SECURITY_CHILD_TABLES
    assert "preferred.contract_terms" in populate_reference_tables.RESEED_CASCADE_TABLES


def test_prune_drops_terms_for_inactive_or_non_preferred_securities():
    from scripts import populate_contract_terms

    statements = []

    class _Result:
        rowcount = 3

    class _Conn:
        def execute(self, statement, *args):
            statements.append(str(statement))
            return _Result()

    pruned = populate_contract_terms._prune_non_preferred_contract_terms(_Conn())

    assert pruned == 3
    assert "s.active IS NOT TRUE" in statements[0]
    assert "LOWER(s.security_type) NOT IN ('preferred', 'preferred stock')" in statements[0]


def test_limited_reference_run_skips_global_identity_query(monkeypatch):
    conn = _Connection([_Result()])
    monkeypatch.setattr(
        populate_reference_tables,
        "engine",
        SimpleNamespace(begin=lambda: conn),
    )

    populate_reference_tables.validate_securities_reference_fk(
        check_active_identity_duplicates=False
    )

    assert len(conn.statements) == 1
    assert "VALIDATE CONSTRAINT fk_securities_company_ticker" in conn.statements[0][0]


def test_full_reference_run_stops_on_duplicate_active_identity(monkeypatch):
    conn = _Connection([_Result(first={"cik": "0001253986", "ticker": "ABR-PD", "active_rows": 2})])
    monkeypatch.setattr(
        populate_reference_tables,
        "engine",
        SimpleNamespace(begin=lambda: conn),
    )

    with pytest.raises(RuntimeError, match="Multiple active reference.securities rows"):
        populate_reference_tables.validate_securities_reference_fk()

    assert len(conn.statements) == 1


# --- a legacy row that already holds the new key's id -------------------------------


def test_the_relabel_targets_only_the_row_holding_the_id_and_never_a_keyed_twin():
    conn = _Connection([_Result()])

    populate_reference_tables._relabel_legacy_holder(
        conn, "the-id", "OCAC", "0001926314", "common_stock", True
    )

    ((sql, params),) = conn.statements
    assert "WHERE s.security_id = :id" in sql
    assert "IS DISTINCT FROM" in sql, "a row that already matches must not be rewritten"
    assert "NOT EXISTS" in sql and "o.security_id <> :id" in sql, (
        "a row already holding the target key is left to the upsert"
    )
    assert (
        "SET ticker" in sql and "security_id =" not in sql.split("SET", 1)[1].split("WHERE")[0]
    ), "the id itself never changes, so no child row moves"
    assert params == {
        "id": "the-id",
        "ticker": "OCAC",
        "cik": "0001926314",
        "type": "common_stock",
        "dividend": True,
    }


def test_upsert_classification_cache_refreshes_row_and_hashes_dividend_facts():
    conn = _Connection([_Result()])
    classification = {
        "security_types": ["preferred_stock"],
        "dividend": False,
        "dividend_last_paid": None,
        "security_titles": ["Ace 7.50% Cum Pref"],
        "security_facts": [],
        "dividend_facts": [{"tag": "DividendsPayableCurrentAndNoncurrent", "records": []}],
        "status": "available",
    }

    populate_reference_tables._upsert_classification_cache(
        conn, "0001891792", "AACU", "Ace Aero Unite", classification
    )

    (sql, params) = conn.statements[0]
    assert "INSERT INTO raw.company_classification" in sql
    assert "ON CONFLICT (cik) DO UPDATE" in sql
    assert params["cik"] == "0001891792"
    assert params["ticker"] == "AACU"
    assert params["dividend"] is False
    expected = hashlib.sha256(
        json.dumps(classification["dividend_facts"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert params["content_hash"] == expected


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM reference.securities LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database
        return None


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
def test_a_row_flipped_in_place_is_relabelled_to_match_its_own_id_and_keeps_its_id():
    """The OCAC collision, reproduced on a real row inside a rolled-back transaction."""
    import uuid

    from sqlalchemy import text

    with _live_engine().connect() as conn:
        outer = conn.begin()
        try:
            row = conn.execute(
                text("""
                SELECT s.security_id, s.ticker, s.cik, s.security_type, s.dividend
                FROM reference.securities s
                WHERE s.active AND s.dividend AND s.cik IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM reference.securities o
                                  WHERE o.cik = s.cik AND o.ticker = s.ticker
                                    AND o.security_id <> s.security_id)
                LIMIT 1""")
            ).one()
            sid, ticker, cik, stype, dividend = row
            assert sid == uuid.uuid5(
                uuid.NAMESPACE_URL, f"dividend-equity:{ticker.upper()}:{cik}:{stype}:{dividend}"
            ), "the fixture row must follow the id convention"

            # The legacy corruption: flag flipped in place, id left as the old key's hash.
            conn.execute(
                text(
                    "UPDATE reference.securities SET dividend = NOT dividend, active = FALSE "
                    "WHERE security_id = :id"
                ),
                {"id": sid},
            )

            populate_reference_tables._relabel_legacy_holder(
                conn, sid, ticker, cik, stype, dividend
            )

            fixed = conn.execute(
                text(
                    "SELECT security_id, dividend FROM reference.securities "
                    "WHERE ticker = :t AND cik = :c"
                ),
                {"t": ticker, "c": cik},
            ).all()
            assert [(r[0], r[1]) for r in fixed] == [(sid, dividend)]
        finally:
            outer.rollback()


# --- the stage must not report success when it stopped early -------------------------


def _run_main(monkeypatch, result):
    import sys

    monkeypatch.setattr(sys, "argv", ["populate_reference_tables", "--securities"])
    monkeypatch.setattr(populate_reference_tables, "populate_securities", lambda *a, **k: result)
    return populate_reference_tables.main()


@pytest.mark.parametrize("tickers", [None, [], ["XRPN", "XRPNW"]])
def test_security_rebuild_scopes_raw_tickers_before_classification(monkeypatch, tickers):
    conn = _Connection([_Result(), _Result()])
    monkeypatch.setattr(populate_reference_tables, "engine", SimpleNamespace(connect=lambda: conn))

    class StopBeforeClassification(Exception):
        pass

    def stop(_conn):
        raise StopBeforeClassification

    monkeypatch.setattr(populate_reference_tables, "observed_payer_keys", stop)
    with pytest.raises(StopBeforeClassification):
        populate_reference_tables.populate_securities(limit=2, tickers=tickers)

    sql, params = conn.statements[1]
    assert ("WHERE ticker = ANY(:tickers)" in sql) == (tickers is not None)
    assert "LIMIT :limit" in sql
    assert params == ({"limit": 2} if tickers is None else {"limit": 2, "tickers": tickers})


def test_targeted_security_cli_normalizes_and_forwards_symbols(monkeypatch):
    import sys

    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["populate_reference_tables", "--securities", "--tickers", " xrpnw,XRPN,xrpn, "],
    )

    def populate(*args, **kwargs):
        calls.append((args, kwargs))
        return 2, 2, 0

    monkeypatch.setattr(populate_reference_tables, "populate_securities", populate)
    assert populate_reference_tables.main() == 0
    assert calls == [
        ((None,), {"repopulate": False, "reclassify": False, "tickers": ["XRPN", "XRPNW"]})
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["--tickers", "XRPN"],
        ["--securities", "--issuers", "--tickers", "XRPN"],
        ["--securities", "--repopulate", "--tickers", "XRPN"],
        ["--securities", "--tickers", " , "],
    ],
)
def test_targeted_security_cli_rejects_invalid_scope(monkeypatch, args):
    import sys

    monkeypatch.setattr(sys, "argv", ["populate_reference_tables", *args])
    with pytest.raises(SystemExit) as exc:
        populate_reference_tables.main()
    assert exc.value.code == 2


def test_targeted_rebuild_cannot_sweep_unrelated_orphans():
    with pytest.raises(ValueError, match="global repopulate sweep"):
        populate_reference_tables.populate_securities(tickers=["XRPN"], repopulate=True)


def test_a_securities_run_that_stopped_early_fails_even_though_it_wrote_rows(monkeypatch, capsys):
    """6,960 rows were written before OCAC aborted the transaction; that is not a success."""
    code = _run_main(monkeypatch, (6971, 6960, populate_reference_tables.MAX_SECURITY_ERRORS + 1))

    assert code == 1
    assert "partially rebuilt" in capsys.readouterr().err


def test_a_few_isolated_errors_do_not_fail_the_stage(monkeypatch):
    assert _run_main(monkeypatch, (6000, 5998, 2)) == 0


def test_an_all_failed_run_still_fails_as_before(monkeypatch):
    assert _run_main(monkeypatch, (5, 0, 5)) == 1


# --- one security's failure is isolated ----------------------------------------------


def test_each_security_runs_in_its_own_savepoint_so_a_failure_cannot_poison_the_next():
    import inspect

    source = inspect.getsource(populate_reference_tables.populate_securities)

    loop = source.split("for sec in raw_tickers:")[1]
    assert loop.index("savepoint = conn.begin_nested()") < loop.index("try:")
    assert loop.index("savepoint.commit()") < loop.index("except Exception")
    assert "savepoint.rollback()" in loop.split("except Exception")[1]
    assert "MAX_SECURITY_ERRORS" in loop and "errors > 10" not in loop
