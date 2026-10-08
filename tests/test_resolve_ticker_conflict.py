"""The ticker/CIK conflict process: the decision rule, the release plan, and the gates.

The decision is a pure function of what SEC's own per-issuer submissions say, so it is
tested as a table. The release is destructive by necessity (deactivating cannot free a
ticker: populate_securities re-activates every company_ticker row each night, and the
foreign key keeps referencing an inactive one), so most of this file is about what it
refuses to do.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from scripts import resolve_ticker_conflict as rtc

# --- the decision ----------------------------------------------------------------


def _subs(*tickers):
    return {"tickers": list(tickers)}


@pytest.mark.parametrize(
    "existing, incoming, expected",
    [
        # SEC itself has moved the ticker: gone from the existing issuer, on the incoming.
        (_subs("ANGX"), _subs("PORT", "PORT-UN"), rtc.STALE),
        # SEC still lists it under the existing issuer and not the incoming one.
        (_subs("ANGX", "PORT-UN"), _subs("PORT"), rtc.INCOMING_WRONG),
        # Both claim it: the case today. Do not guess.
        (_subs("ANGX", "PORT-UN"), _subs("PORT", "PORT-UN"), rtc.AMBIGUOUS),
        # Neither claims it.
        (_subs("ANGX"), _subs("PORT"), rtc.AMBIGUOUS),
        # An issuer's submissions are unavailable: unknown is not evidence either way.
        (None, _subs("PORT-UN"), rtc.AMBIGUOUS),
        (_subs("ANGX"), None, rtc.AMBIGUOUS),
        (None, None, rtc.AMBIGUOUS),
        # An empty ticker list is not "lists nothing": SEC leaves it empty for a
        # registrant it has not populated yet. Unknown, never evidence of absence.
        ({"tickers": []}, _subs("PORT-UN"), rtc.AMBIGUOUS),
        ({}, _subs("PORT-UN"), rtc.AMBIGUOUS),
        (_subs("ANGX", "PORT-UN"), {"tickers": []}, rtc.AMBIGUOUS),
        (_subs("ANGX", "PORT-UN"), {}, rtc.AMBIGUOUS),
    ],
)
def test_the_classification_follows_what_sec_says_about_each_issuer(existing, incoming, expected):
    assert rtc.classify("PORT-UN", existing, incoming) == expected


def test_a_brand_new_registrant_with_no_listed_tickers_is_not_called_wrong():
    """The 2026-10-06 PORT-UN review.

    Southport II's units began trading that week and its SEC submissions had an empty
    ticker list. That read as "does not list PORT-UN", which classified a mapping SEC's
    own company file and the issuer's filings support as INCOMING_WRONG.
    """
    angel = _subs("ANGX", "PORT-UN")  # still carries Southport I's old unit symbol
    southport_ii = {"tickers": [], "exchanges": []}

    assert rtc.classify("PORT-UN", angel, southport_ii) == rtc.AMBIGUOUS
    assert rtc.classify("PORT-UN", angel, southport_ii) != rtc.INCOMING_WRONG


def test_the_comparison_ignores_case_and_whitespace():
    assert rtc.classify("PORT-UN", _subs("angx"), _subs(" port-un ")) == rtc.STALE


def test_the_one_sided_unknown_never_reads_as_stale():
    """Only a *known* absence from the existing issuer can make a mapping stale."""
    assert rtc.lists_ticker(None, "X") is None
    assert rtc.lists_ticker({"tickers": []}, "X") is None
    assert rtc.classify("X", None, _subs("X")) != rtc.STALE
    assert rtc.classify("X", {"tickers": []}, _subs("X")) != rtc.STALE


# --- what a release would remove -------------------------------------------------


def _fk(child, parent, child_cols=("security_id",), parent_cols=("security_id",)):
    return {
        "child": child,
        "parent": parent,
        "child_cols": list(child_cols),
        "parent_cols": list(parent_cols),
    }


SECURITIES = "reference.securities"
FKS = [
    _fk("raw.market_data", SECURITIES),
    _fk("raw.sec_documents", SECURITIES),
    # two levels down
    _fk("preferred.security_terms", "raw.sec_documents", ("source_document_id",), ("document_id",)),
    # a table with two doomed parents
    _fk("clean.company_profile", SECURITIES, ("reference_security_id",), ("security_id",)),
    _fk(
        "clean.company_profile",
        "raw.ticker_profile",
        ("source_profile_security_id",),
        ("security_id",),
    ),
    _fk("raw.ticker_profile", SECURITIES),
    # composite key
    _fk(
        "clean.company_officer",
        "clean.company_profile",
        ("symbol", "parent_name"),
        ("symbol", "parent_name"),
    ),
    # the root's own parent: points away from the doomed set and must be ignored
    _fk(SECURITIES, "raw.company_ticker", ("ticker", "cik"), ("ticker", "cik")),
    # unrelated to the root
    _fk("model.other_child", "model.other_parent"),
    # self reference
    _fk("raw.sec_documents", "raw.sec_documents", ("parent_id",), ("document_id",)),
]


def test_only_tables_that_depend_on_the_root_are_in_the_plan():
    order, _edges = rtc.dependent_graph(FKS)

    assert set(order) == {
        SECURITIES,
        "raw.market_data",
        "raw.sec_documents",
        "preferred.security_terms",
        "clean.company_profile",
        "raw.ticker_profile",
        "clean.company_officer",
    }
    assert "raw.company_ticker" not in order and "model.other_child" not in order


def test_every_table_is_deleted_before_the_table_it_references():
    order, _edges = rtc.dependent_graph(FKS)

    for fk in FKS:
        if fk["child"] in order and fk["parent"] in order and fk["child"] != fk["parent"]:
            assert order.index(fk["child"]) < order.index(fk["parent"]), fk
    assert order[-1] == SECURITIES, "the root must go last"


def test_a_foreign_key_cycle_is_refused_rather_than_ordered_wrongly():
    cyclic = [_fk("a.x", SECURITIES), _fk("a.y", "a.x"), _fk("a.x", "a.y")]

    with pytest.raises(RuntimeError, match="cycle"):
        rtc.dependent_graph(cyclic)


def test_the_predicate_follows_each_path_to_a_doomed_row():
    _order, edges = rtc.dependent_graph(FKS)

    root = rtc.doomed_predicate(SECURITIES, edges)
    two_level = rtc.doomed_predicate("preferred.security_terms", edges)
    two_parents = rtc.doomed_predicate("clean.company_profile", edges)
    composite = rtc.doomed_predicate("clean.company_officer", edges)

    assert "ANY(:sids)" in root
    assert two_level.count("EXISTS") == 2 and "document_id" in two_level
    assert " OR " in two_parents, "a row is doomed if EITHER parent is"
    assert "symbol" in composite and "parent_name" in composite and " AND " in composite


# --- the release gates ------------------------------------------------------------

CONFLICT = {
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


def _report(classification):
    return {
        "conflict": CONFLICT,
        "classification": classification,
        "existing_issuer_lists_ticker": False,
        "incoming_issuer_lists_ticker": True,
        "existing_submissions": {"source": "sec_live", "retrieved": "t", "tickers": ["ANGX"]},
        "incoming_submissions": {"source": "sec_live", "retrieved": "t", "tickers": ["PORT-UN"]},
        "existing_issuer_other_tickers": ["ANGX"],
        "existing_securities": [],
    }


PLAN = {
    "security_ids": ["sid-1"],
    "tables": [{"table": "raw.market_data", "predicate": "p", "rows": 5}],
}


class _Harness:
    """Patches everything the release touches so only its decisions are under test."""

    def __init__(self, classification, conflicts=(CONFLICT,), plan=PLAN, lock=None):
        self.perform = MagicMock(return_value={"raw.market_data": 5})
        self.acquire = MagicMock(side_effect=lock) if isinstance(lock, Exception) else MagicMock()
        self.release = MagicMock()
        self.patches = [
            patch.object(rtc, "_load_snapshot_entries", return_value=[]),
            patch.object(rtc, "current_conflicts", return_value=list(conflicts)),
            patch.object(rtc, "evidence_for", return_value=_report(classification)),
            patch.object(rtc, "plan_release", return_value=plan),
            patch.object(rtc, "perform_release", self.perform),
            patch.object(rtc, "_acquire_run_lock", self.acquire),
            patch.object(rtc, "_release_run_lock", self.release),
            patch.object(rtc, "engine", MagicMock()),
            patch.object(rtc, "ARCHIVE_DIR", MagicMock()),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


def _release(*args):
    return rtc.main(["release", "--ticker", "PORT-UN", "--reviewed-by", "ops", *args])


def test_a_release_is_a_dry_run_unless_executed():
    with _Harness(rtc.STALE) as h:
        code = _release()

    assert code == 0
    h.perform.assert_not_called()
    h.acquire.assert_not_called()


def test_executing_requires_the_ticker_to_be_repeated():
    with _Harness(rtc.STALE) as h:
        code = _release("--execute")
        wrong = _release("--execute", "--confirm", "ANGX")

    assert code == 2 and wrong == 2
    h.perform.assert_not_called()


def test_a_stale_conflict_is_released_under_the_pipeline_lock():
    with _Harness(rtc.STALE) as h:
        code = _release("--execute", "--confirm", "PORT-UN")

    assert code == 0
    h.perform.assert_called_once()
    h.acquire.assert_called_once()
    h.release.assert_called_once()  # the lock is released after the work


def test_a_conflict_where_sec_keeps_the_existing_mapping_is_never_released():
    with _Harness(rtc.INCOMING_WRONG) as h:
        code = _release("--execute", "--confirm", "PORT-UN", "--basis", "I am sure")

    assert code == 1
    h.perform.assert_not_called()


def test_an_ambiguous_conflict_needs_the_evidence_named():
    with _Harness(rtc.AMBIGUOUS) as h:
        without = _release("--execute", "--confirm", "PORT-UN")
        with_basis = _release(
            "--execute", "--confirm", "PORT-UN", "--basis", "NYSE notice 2026-10-01"
        )

    assert without == 1 and with_basis == 0
    h.perform.assert_called_once()
    header, note = h.perform.call_args.args[4], h.perform.call_args.args[5]
    assert header["basis"] == "NYSE notice 2026-10-01"
    assert "NYSE notice 2026-10-01" in note, "the basis must reach the registry note"


def test_a_release_during_a_nightly_is_refused():
    with _Harness(rtc.STALE, lock=rtc.PipelineAlreadyRunning("busy")) as h:
        code = _release("--execute", "--confirm", "PORT-UN")

    assert code == 2
    h.perform.assert_not_called()


def test_a_ticker_with_no_open_conflict_is_not_released():
    with _Harness(rtc.STALE, conflicts=()) as h:
        code = _release("--execute", "--confirm", "PORT-UN")

    assert code == 1
    h.perform.assert_not_called()


def test_a_conflict_with_no_securities_row_is_not_released():
    with _Harness(rtc.STALE, plan={"security_ids": [], "tables": []}) as h:
        code = _release("--execute", "--confirm", "PORT-UN")

    assert code == 1
    h.perform.assert_not_called()


# --- the release itself, against a recording connection ----------------------------


class _Result:
    def __init__(self, rows=(), rowcount=0, scalar=None):
        self._rows, self.rowcount, self._scalar = list(rows), rowcount, scalar

    def scalars(self):
        return iter(self._rows)

    def scalar(self):
        return self._scalar


class _RecordingConn:
    def __init__(self, archive_path, counts, deleted=None, still_referenced=0):
        self.archive_path = archive_path
        self.counts = counts
        self.deleted = deleted or counts
        self.still_referenced = still_referenced
        self.log = []
        self.archive_existed_at_first_delete = None

    def execute(self, stmt, params=None):
        sql = str(stmt)
        table = sql.split(" FROM ")[1].split()[0] if " FROM " in sql else None
        if "to_jsonb" in sql:
            self.log.append(("archive", table))
            return _Result([{"row": i} for i in range(self.counts[table])])
        if sql.lstrip().startswith("DELETE"):
            if self.archive_existed_at_first_delete is None:
                self.archive_existed_at_first_delete = self.archive_path.exists()
            self.log.append(("delete", table))
            return _Result(rowcount=self.deleted[table])
        if "count(*) FROM reference.securities" in sql:
            return _Result(scalar=self.still_referenced)
        if "INSERT INTO audit.quarantined_values" in sql:
            self.log.append(("registry", params["observed"]))
            return _Result()
        raise AssertionError(f"unexpected statement: {sql}")


MULTI = {
    "security_ids": ["sid-1"],
    "tables": [
        {"table": "preferred.security_terms", "predicate": "p", "rows": 1},
        {"table": "raw.market_data", "predicate": "p", "rows": 5},
        {"table": "reference.securities", "predicate": "p", "rows": 1},
    ],
}
COUNTS = {"preferred.security_terms": 1, "raw.market_data": 5, "reference.securities": 1}


def test_every_row_is_archived_to_disk_before_any_is_deleted(tmp_path):
    path = tmp_path / "archive.json"
    conn = _RecordingConn(path, COUNTS)

    rtc.perform_release(conn, CONFLICT, MULTI, path, {"reviewed_by": "ops"}, "note")

    kinds = [kind for kind, _ in conn.log]
    assert kinds.index("delete") > max(i for i, k in enumerate(kinds) if k == "archive")
    assert conn.archive_existed_at_first_delete is True, "the archive must exist before deleting"
    body = json.loads(path.read_text())
    assert body["header"] == {"reviewed_by": "ops"}
    assert {t: len(r) for t, r in body["rows"].items()} == COUNTS


def test_children_are_deleted_before_their_parents_and_the_registry_is_written_last(tmp_path):
    path = tmp_path / "archive.json"
    conn = _RecordingConn(path, COUNTS)

    rtc.perform_release(conn, CONFLICT, MULTI, path, {}, "note")

    deletes = [t for kind, t in conn.log if kind == "delete"]
    assert deletes == ["preferred.security_terms", "raw.market_data", "reference.securities"]
    assert conn.log[-1] == ("registry", "PORT-UN")


def test_a_delete_that_removes_a_different_number_of_rows_aborts(tmp_path):
    path = tmp_path / "archive.json"
    conn = _RecordingConn(path, COUNTS, deleted={**COUNTS, "raw.market_data": 4})

    with pytest.raises(RuntimeError, match="deleted 4 rows, planned 5"):
        rtc.perform_release(conn, CONFLICT, MULTI, path, {}, "note")

    assert not any(kind == "registry" for kind, _ in conn.log)


def test_a_release_that_leaves_the_stale_row_referenced_aborts(tmp_path):
    path = tmp_path / "archive.json"
    conn = _RecordingConn(path, COUNTS, still_referenced=1)

    with pytest.raises(RuntimeError, match="still referenced"):
        rtc.perform_release(conn, CONFLICT, MULTI, path, {}, "note")

    assert not any(kind == "registry" for kind, _ in conn.log)


def test_a_failed_archive_stops_the_release_before_anything_is_deleted(tmp_path):
    path = tmp_path / "missing_dir" / "archive.json"
    conn = _RecordingConn(path, COUNTS)

    with patch.object(rtc, "archive_rows", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            rtc.perform_release(conn, CONFLICT, MULTI, path, {}, "note")

    assert conn.log == []


# --- against the real schema ------------------------------------------------------


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
def test_a_release_against_the_real_schema_removes_exactly_the_stale_rows(tmp_path):
    """Synthesises a conflict inside a transaction that is always rolled back.

    The foreign-key graph, the delete order, the two-level chain through
    raw.sec_documents and the registry insert all run against the live schema, so a
    table added later that references reference.securities is exercised here without
    anyone updating a list.
    """
    from sqlalchemy import text

    stale, other = str(uuid.uuid4()), str(uuid.uuid4())
    conflict = {**CONFLICT, "ticker": "ZZTESTUN", "existing_cik": "9999999991"}
    path = tmp_path / "archive.json"

    with _live_engine().connect() as conn:
        outer = conn.begin()
        try:
            conn.execute(
                text("""
                INSERT INTO raw.company_ticker (ticker, cik, title, raw_payload)
                VALUES ('ZZTESTUN', '9999999991', 'Old Co', '{}'::jsonb),
                       ('ZZTESTKEEP', '9999999991', 'Old Co', '{}'::jsonb)
            """)
            )
            conn.execute(
                text("""
                INSERT INTO reference.securities (ticker, cik, security_id, security_name,
                                                  security_type, dividend, active)
                VALUES ('ZZTESTUN', '9999999991', :stale, 'Old Co unit', 'common_stock', FALSE, TRUE),
                       ('ZZTESTKEEP', '9999999991', :other, 'Old Co common', 'common_stock', FALSE, TRUE)
            """),
                {"stale": stale, "other": other},
            )
            conn.execute(
                text("""
                INSERT INTO raw.market_data (security_id, observation_date, provider)
                VALUES (:stale, '2026-01-02', 'TEST'), (:stale, '2026-01-05', 'TEST'),
                       (:other, '2026-01-02', 'TEST')
            """),
                {"stale": stale, "other": other},
            )
            document = conn.execute(
                text("""
                INSERT INTO raw.sec_documents (security_id, cik)
                VALUES (:stale, '9999999991') RETURNING document_id
            """),
                {"stale": stale},
            ).scalar()
            conn.execute(
                text("""
                INSERT INTO preferred.security_terms (security_id, source_document_id)
                VALUES (:stale, :doc)
            """),
                {"stale": stale, "doc": document},
            )

            plan = rtc.plan_release(conn, conflict)
            rows = {t["table"]: t["rows"] for t in plan["tables"] if t["rows"]}
            assert plan["security_ids"] == [stale]
            assert rows == {
                "raw.market_data": 2,
                "raw.sec_documents": 1,
                "preferred.security_terms": 1,
                "reference.securities": 1,
            }

            rtc.perform_release(conn, conflict, plan, path, {"reviewed_by": "test"}, "note")

            def count(sql, **params):
                return conn.execute(text(sql), params).scalar()

            assert (
                count("SELECT count(*) FROM reference.securities WHERE security_id = :s", s=stale)
                == 0
            )
            assert (
                count("SELECT count(*) FROM raw.market_data WHERE security_id = :s", s=stale) == 0
            )
            # The sibling ticker of the same issuer is untouched.
            assert (
                count("SELECT count(*) FROM reference.securities WHERE security_id = :s", s=other)
                == 1
            )
            assert (
                count("SELECT count(*) FROM raw.market_data WHERE security_id = :s", s=other) == 1
            )
            assert (
                count(
                    "SELECT count(*) FROM audit.quarantined_values WHERE row_key = :s "
                    "AND rule = 'TICKER_CIK_CONFLICT' AND resolved_at IS NOT NULL",
                    s=stale,
                )
                == 1
            )
            assert len(json.loads(path.read_text())["rows"]["raw.market_data"]) == 2
        finally:
            outer.rollback()

        leftover = conn.execute(
            text("SELECT count(*) FROM reference.securities WHERE ticker LIKE 'ZZTEST%'")
        ).scalar()
    assert leftover == 0, "the test must leave no trace"
