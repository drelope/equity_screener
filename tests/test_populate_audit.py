"""Audit backfills must scope to the active universe.

Deactivated tickers (former payers that flipped security_id) otherwise dilute
audit.source_lineage and audit.data_quality coverage/quality metrics with rows
that are no longer part of the pipeline.
"""

from datetime import date

import pytest

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


def _normalized_data_quality_sql():
    conn = _FakeConnection()
    populate_audit.data_quality(conn, date(2026, 10, 3))
    return " ".join(conn.statements[0].split())


def _live_connection():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


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


def test_data_quality_reliability_is_provider_based():
    """WS4 item 9: the profile's reliability must come from the provider, and
    companyfacts (SEC XBRL) is a source on its own, not gated on a profile."""
    sql = _normalized_data_quality_sql()
    assert "COALESCE(:openbb_reliability, 0.9)" in sql
    assert "COALESCE(:yfinance_reliability, 0.8)" in sql
    assert "COALESCE(:sec_reliability, 1.0)" in sql


def test_data_quality_companyfacts_is_a_source_not_a_zero():
    """A non-dividend payer with companyfacts must score instead of reading
    'no data': source_reliability is GREATEST(profile provider, SEC XBRL when a
    companyfacts row exists)."""
    sql = _normalized_data_quality_sql()
    assert "CASE WHEN cf.cik IS NOT NULL THEN COALESCE(:sec_reliability, 1.0) ELSE 0.0 END" in sql
    assert "WHEN COALESCE(q.source_reliability, 0) = 0 THEN 'no data'" in sql


def test_data_quality_consistency_normalises_security_type():
    """WS4 item 8: compare the normalised reference class, not the raw OpenBB
    wording, so 'Common Stock, par value $0.01 per share' agrees with
    common_stock instead of being penalised for the spelling."""
    sql = _normalized_data_quality_sql()
    assert "LOWER(tp.security_type) LIKE '%common%'" in sql
    assert "LOWER(s.security_type) LIKE '%common%'" in sql
    assert "LOWER(tp.security_type) = LOWER(s.security_type)" not in sql


def test_data_quality_no_data_means_no_source_at_all():
    """Re-score the newest snapshot with the whole-universe formula, then pin
    the invariant that 'no data' means a truly sourceless security: neither
    raw.companyfacts nor raw.ticker_profile."""
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.begin() as conn:
        latest = conn.execute(text("SELECT max(as_of_date) FROM audit.data_quality")).scalar()
        if latest is None:
            pytest.skip("audit.data_quality is empty")

        populate_audit.data_quality(conn, latest)

        bad = conn.execute(
            text("""
                SELECT count(*) FROM audit.data_quality dq
                LEFT JOIN reference.securities s ON s.security_id = dq.security_id
                LEFT JOIN raw.companyfacts cf ON cf.cik = s.cik
                LEFT JOIN raw.ticker_profile tp ON tp.security_id = dq.security_id
                WHERE dq.as_of_date = :as_of AND dq.status = 'no data'
                  AND (cf.cik IS NOT NULL OR tp.security_id IS NOT NULL OR s.security_id IS NULL)
                """),
            {"as_of": latest},
        ).scalar()
    assert bad == 0


def test_data_quality_clamps_recency_to_one():
    """as_of is midnight but a row retrieved later that same day is newer than
    the as-of instant, so the unbounded formula scored recency above 1.0."""
    # Scope to the LATERAL subquery: the outer SELECT aliases the aggregate
    # "AS recency" first, which would cut this block off before the CASE.
    lateral = _normalized_data_quality_sql().split("CROSS JOIN LATERAL")[1]
    recency = lateral.split("END AS recency")[0]
    # Both the ticker_profile and companyfacts branches must be clamped.
    assert recency.count("LEAST(1.0, GREATEST(0.0") == 2
    # The old unclamped form must be gone.
    assert "THEN GREATEST(0.0, 1.0 - EXTRACT" not in recency


def test_data_quality_components_stay_within_the_unit_interval():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        latest = conn.execute(text("SELECT max(as_of_date) FROM audit.data_quality")).scalar()
        if latest is None:
            pytest.skip("audit.data_quality is empty")
        over = conn.execute(
            text("""
            SELECT count(*) FROM audit.data_quality
            WHERE as_of_date = :as_of
              AND (source_reliability > 1 OR source_reliability < 0
                   OR completeness > 1 OR completeness < 0
                   OR recency > 1 OR recency < 0
                   OR consistency > 1 OR consistency < 0
                   OR quality_score > 1 OR quality_score < 0)
            """),
            {"as_of": latest},
        ).scalar()
    assert over == 0, f"{over} component(s) outside [0,1] on {latest}"
