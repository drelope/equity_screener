"""preferred.issuer_terms must expose issuer-level SEC terms without promoting them.

The per-series term columns on clean.ticker_profile are NULL by design: SEC
Company Facts are filed per issuer and carry no member dimension, so a coupon
rate or liquidation amount read from them cannot be attributed to one preferred
class. These tests pin that the evidence stays reachable and stays honestly
labelled, so a future change cannot quietly reintroduce false precision.
"""

from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[1] / "sql" / "migrations" / "V0032_issuer_terms_view.sql"
)


def _live_connection():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def test_view_is_defined_in_schema_and_migration():
    schema = (Path(__file__).resolve().parents[1] / "sql" / "schema.sql").read_text()
    assert "CREATE OR REPLACE VIEW preferred.issuer_terms" in schema
    assert "CREATE OR REPLACE VIEW preferred.issuer_terms" in MIGRATION.read_text()


def test_liquidation_column_is_not_labelled_as_a_liquidation_preference():
    """extract_preferred_terms_from_companyfacts falls back to the par/stated
    value concepts and stores both under one key, so naming the column
    "liquidation_preference" would assert a precision the source lacks."""
    ddl = MIGRATION.read_text()
    assert "issuer_liquidation_or_par_value" in ddl
    assert "AS liquidation_preference" not in ddl


def test_view_is_declared_at_issuer_granularity():
    ddl = MIGRATION.read_text()
    assert "'issuer_level_unallocated'::TEXT AS terms_scope" in ddl
    # Grouped by CIK, never by security_id: one row per issuer.
    assert "GROUP BY LPAD(BTRIM(s.cik), 10, '0'), i.issuer_name" in ddl


def _sql_body(sql):
    """Strip ``--`` comment lines so prose cannot satisfy or break assertions."""
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _view_statement():
    """Just the CREATE VIEW statement, excluding the COMMENT ON block after it.

    Those comments legitimately name clean.ticker_profile while explaining why
    it is *not* written to, so they must stay out of this assertion.
    """
    for statement in _sql_body(MIGRATION.read_text()).split(";"):
        if "CREATE OR REPLACE VIEW" in statement:
            return statement.lower()
    raise AssertionError("view definition not found in migration")


def test_view_does_not_write_to_clean_ticker_profile():
    """The view must be read-only w.r.t. the curated layer; the whole point is
    that clean.ticker_profile keeps NULL per-series values."""
    ddl = _view_statement()
    assert "insert" not in ddl
    assert "update " not in ddl
    assert "delete" not in ddl
    assert "clean.ticker_profile" not in ddl


def test_view_reads_only_the_profile_and_reference_tables():
    ddl = _view_statement()
    assert "raw.ticker_profile" in ddl
    assert "reference.securities" in ddl
    assert "raw.companyfacts" not in ddl, "the extractor already staged the terms"


def test_view_rows_are_issuer_scoped_in_the_live_database():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('preferred.issuer_terms') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("preferred.issuer_terms not applied (run scripts.migrate)")

        total, bad_scope, conflicts, multi = conn.execute(
            text("""
            SELECT count(*),
                   count(*) FILTER (WHERE terms_scope <> 'issuer_level_unallocated'),
                   count(*) FILTER (WHERE distinct_coupon_values > 1
                                       OR distinct_liquidation_values > 1),
                   count(*) FILTER (WHERE security_count > 1)
            FROM preferred.issuer_terms
            """)
        ).one()

    assert total >= 0
    assert bad_scope == 0, "every row must declare issuer_level_unallocated scope"
    assert conflicts == 0, "per-security extraction disagreed within a CIK"
    # Ambiguity is exposed rather than hidden; a non-zero count here is the
    # reason the terms cannot be joined onto a single series.
    assert multi >= 0
