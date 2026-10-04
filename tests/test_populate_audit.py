"""Audit backfills must scope to the active universe.

Deactivated tickers (former payers that flipped security_id) otherwise dilute
audit.source_lineage and audit.data_quality coverage/quality metrics with rows
that are no longer part of the pipeline.
"""

from datetime import date

from scripts import populate_audit


class _Result:
    rowcount = 1


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result()


def _insert_sql(conn):
    statement = next(s for s in conn.statements if "INSERT" in s)
    return " ".join(statement.split())


def test_source_lineage_scopes_every_branch_to_active_securities():
    conn = _FakeConnection()

    populate_audit.source_lineage(conn, date(2026, 10, 3))

    sql = _insert_sql(conn)
    assert (
        "JOIN reference.securities s ON s.security_id = tp.security_id AND s.active = TRUE" in sql
    )
    assert "JOIN reference.securities s ON s.cik = cf.cik AND s.active = TRUE" in sql
    assert "FROM reference.securities s WHERE s.active = TRUE" in sql


def test_data_quality_scopes_to_active_securities():
    conn = _FakeConnection()

    populate_audit.data_quality(conn, date(2026, 10, 3))

    assert "WHERE s.active = TRUE" in conn.statements[0]
