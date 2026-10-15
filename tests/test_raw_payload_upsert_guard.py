"""The raw JSONB upserts skip the payload rewrite when the content is unchanged.

``raw.companyfacts`` and friends keep ``retrieved_at`` as a refresh clock: every
re-fetch advances it even when the payload is byte-identical. That is deliberate,
but it used to be implemented as an unconditional ``raw_payload = EXCLUDED.raw_payload``,
so a nightly re-fetch rewrote the whole multi-megabyte JSON -- a fresh TOAST copy
every run, doubling the table's on-disk size in dead chunks. The guard keeps the
clock advancing while leaving the stored payload in place when ``content_hash``
matches.
"""

import pytest
from sqlalchemy import text

from scripts.populate_companyfacts import upsert_companyfacts, upsert_submissions


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM raw.companyfacts LIMIT 1")
        return engine
    except Exception:  # pragma: no cover - no database
        return None


pytestmark = pytest.mark.skipif(_live_engine() is None, reason="no live database")

_CIK = "0000000001"


def _companyfacts(tag, filler):
    return {
        "company": "Test Co",
        "full_facts": {"facts": {"x": tag, "blob": filler}},
        "concept_groups": {"preferred_stock": [tag]},
    }


def test_companyfacts_identical_payload_is_not_rewritten_but_clock_advances(db_conn):
    payload = _companyfacts("A", "x" * 200_000)
    upsert_companyfacts(db_conn, _CIK, payload)
    first = db_conn.execute(
        text(
            "SELECT raw_payload::text AS p, content_hash, retrieved_at "
            "FROM raw.companyfacts WHERE cik = :cik"
        ),
        {"cik": _CIK},
    ).one()

    upsert_companyfacts(db_conn, _CIK, payload)
    second = db_conn.execute(
        text(
            "SELECT raw_payload::text AS p, content_hash, retrieved_at "
            "FROM raw.companyfacts WHERE cik = :cik"
        ),
        {"cik": _CIK},
    ).one()

    assert first.p == second.p
    assert first.content_hash == second.content_hash
    assert second.retrieved_at >= first.retrieved_at


def test_companyfacts_changed_payload_is_applied(db_conn):
    upsert_companyfacts(db_conn, _CIK, _companyfacts("A", "x" * 1000))
    first = db_conn.execute(
        text("SELECT content_hash FROM raw.companyfacts WHERE cik = :cik"), {"cik": _CIK}
    ).one()

    upsert_companyfacts(db_conn, _CIK, _companyfacts("B", "y" * 1000))
    second = db_conn.execute(
        text("SELECT raw_payload::text AS p, content_hash FROM raw.companyfacts WHERE cik = :cik"),
        {"cik": _CIK},
    ).one()

    assert "B" in second.p
    assert second.content_hash != first.content_hash


def test_submissions_identical_payload_is_not_rewritten_but_clock_advances(db_conn):
    payload = {"name": "Test Co", "filings": {"recent": {"form": ["10-Q"] * 1000}}}
    upsert_submissions(db_conn, _CIK, "Test Co", payload)
    first = db_conn.execute(
        text(
            "SELECT raw_payload::text AS p, content_hash, retrieved_at "
            "FROM raw.sec_submissions WHERE cik = :cik"
        ),
        {"cik": _CIK},
    ).one()

    upsert_submissions(db_conn, _CIK, "Test Co", payload)
    second = db_conn.execute(
        text(
            "SELECT raw_payload::text AS p, content_hash, retrieved_at "
            "FROM raw.sec_submissions WHERE cik = :cik"
        ),
        {"cik": _CIK},
    ).one()

    assert first.p == second.p
    assert first.content_hash == second.content_hash
    assert second.retrieved_at >= first.retrieved_at
