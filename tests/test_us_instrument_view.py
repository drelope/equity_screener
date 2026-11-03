"""The US-instrument rule lives in one view; pin its semantics against the live catalog."""

import pytest
from sqlalchemy import text


def _conn():
    try:
        from src.crispdm.db import engine

        conn = engine.connect()
        conn.exec_driver_sql("SELECT 1 FROM reference.v_us_instruments LIMIT 1")
        return conn
    except Exception:  # pragma: no cover - environments without the database
        return None


@pytest.fixture
def conn():
    c = _conn()
    if c is None:
        pytest.skip("no database available")
    yield c
    c.close()


def _count(conn, where):
    return conn.execute(
        text(f"SELECT count(*) FROM reference.v_us_instruments WHERE {where}")
    ).scalar()  # noqa: S608


def test_a_us_exchange_usd_listing_is_us_whatever_its_address(conn):
    assert _count(conn, "us_basis = 'us_exchange_usd' AND NOT is_us_instrument") == 0
    assert _count(conn, "exchange_code = 'NYSE' AND currency = 'USD' AND NOT is_us_instrument") == 0


def test_an_otc_listing_is_us_only_with_a_us_business_address(conn):
    assert _count(conn, "exchange_code = 'PINK' AND us_basis = 'us_exchange_usd'") == 0
    assert _count(conn, "us_basis = 'us_business_address' AND exchange_code <> 'PINK'") >= 0
    assert _count(conn, "us_basis = 'non_us' AND is_us_instrument") == 0


def test_a_missing_address_is_unknown_not_silently_us_or_non_us(conn):
    assert (
        _count(
            conn,
            "business_state_or_country IS NULL AND us_basis NOT IN ('unknown', 'us_exchange_usd')",
        )
        == 0
    )
    assert _count(conn, "us_basis = 'unknown' AND is_us_instrument") == 0


def test_a_non_usd_security_is_never_a_us_instrument(conn):
    assert _count(conn, "currency IS DISTINCT FROM 'USD' AND is_us_instrument") == 0
