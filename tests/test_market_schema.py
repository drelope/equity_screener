"""The reserved intraday schema (V0072).

The market schema is empty by design: the pipeline is nightly-batch and
intraday data is out of scope for the MVP. V0072 declares the shapes a future
intraday source lands in, month-partitioned on ts, without wiring any
acquisition. These tests hold that shape in place and cover the two things that
made it non-obvious: a partitioned table's foreign keys are copied onto every
partition under the same name (which collided in the drift fingerprint), and the
DEFAULT partition is what makes the tables writable before a month exists.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM market.bar LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database
        return None


pytestmark = pytest.mark.skipif(_live_engine() is None, reason="no live database")

_TABLES = ("trade", "quote", "bar")


def _relation_kinds(conn):
    return dict(
        conn.execute(
            text(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace ns ON ns.oid = c.relnamespace "
                "WHERE ns.nspname = 'market'"
            )
        ).all()
    )


def _one_security(conn):
    return conn.execute(text("SELECT security_id FROM reference.securities LIMIT 1")).scalar()


class TestShape:
    @pytest.mark.parametrize("table", _TABLES)
    def test_each_table_is_a_partitioned_parent(self, db_conn, table):
        assert _relation_kinds(db_conn)[table] == "p"

    @pytest.mark.parametrize("table", _TABLES)
    def test_each_table_has_a_default_partition(self, db_conn, table):
        bound = db_conn.execute(
            text(
                "SELECT pg_get_expr(c.relpartbound, c.oid) FROM pg_class c "
                "JOIN pg_namespace ns ON ns.oid = c.relnamespace "
                "WHERE ns.nspname = 'market' AND c.relname = :name"
            ),
            {"name": f"{table}_default"},
        ).scalar()
        assert bound == "DEFAULT"

    @pytest.mark.parametrize("table", _TABLES)
    def test_tables_are_empty(self, db_conn, table):
        assert db_conn.execute(text(f"SELECT count(*) FROM market.{table}")).scalar() == 0

    @pytest.mark.parametrize("table", _TABLES)
    def test_partition_key_is_range_on_ts(self, db_conn, table):
        keydef = db_conn.execute(
            text(f"SELECT pg_get_partkeydef('market.{table}'::regclass)")
        ).scalar()
        assert keydef == "RANGE (ts)"


class TestRouting:
    def test_a_row_before_any_month_partition_lands_in_default(self, db_conn):
        security = _one_security(db_conn)
        db_conn.execute(
            text(
                "INSERT INTO market.bar (security_id, interval, ts, close, provider) "
                "VALUES (:sid, '1m', '2001-01-02T09:30:00Z', 12.5, 'TEST')"
            ),
            {"sid": security},
        )
        landed = db_conn.execute(
            text("SELECT tableoid::regclass::text FROM market.bar WHERE provider = 'TEST'")
        ).scalar()
        assert landed == "market.bar_default"

    def test_trade_allows_two_prints_at_the_same_microsecond(self, db_conn):
        """The identity column is why (security_id, ts) is not the trade key."""
        security = _one_security(db_conn)
        insert = text(
            "INSERT INTO market.trade (security_id, ts, price, provider) "
            "VALUES (:sid, '2001-01-02T09:30:00.000001Z', :px, 'TEST')"
        )
        db_conn.execute(insert, {"sid": security, "px": 10.0})
        db_conn.execute(insert, {"sid": security, "px": 10.01})
        count = db_conn.execute(
            text("SELECT count(*) FROM market.trade WHERE provider = 'TEST'")
        ).scalar()
        assert count == 2

    def test_unknown_security_is_rejected_by_the_foreign_key(self, db_conn):
        with pytest.raises(IntegrityError):
            db_conn.execute(
                text(
                    "INSERT INTO market.quote (security_id, ts, bid, provider) "
                    "VALUES ('00000000-0000-0000-0000-000000000000', "
                    "'2001-01-02T09:30:00Z', 1.0, 'TEST')"
                )
            )


class TestFingerprint:
    """Partition-local objects must not reach the drift fingerprint.

    A partitioned table's foreign key is copied onto each partition under the
    parent's constraint name, and each partition carries a copy of every index.
    The fingerprint keys constraints by name, so the parent's row and the copy's
    row collide on one key and the winner depends on physical order -- the drift
    check then reports a disagreement between a database and itself.
    """

    def test_parent_constraints_are_fingerprinted_not_partition_copies(self, db_conn):
        from src.crispdm.schema_fingerprint import fingerprint

        fp = fingerprint(db_conn)
        for table in _TABLES:
            assert fp[f"constraint market.{table}_security_id_fkey"] == (
                f"ON market.{table} FOREIGN KEY (security_id) "
                "REFERENCES reference.securities(security_id)"
            )

    def test_partition_children_are_absent_from_the_fingerprint(self, db_conn):
        from src.crispdm.schema_fingerprint import fingerprint

        fp = fingerprint(db_conn)
        assert "relation market.bar" in fp
        assert "relation market.bar_default" not in fp
        assert not any("_default" in key for key in fp)
