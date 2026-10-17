"""preferred.v_security_terms is the one place the Screener and Security detail
page read preferred terms and the latest dividend event from.

The two consumers used to compute those lookups separately and could disagree.
These tests pin the two properties that make the view trustworthy, and that a
future change cannot quietly undo:

* liquidation preference is per-series evidence only, range-guarded, and never
  the issuer-level par/aggregate in preferred.issuer_terms (which cannot be
  attributed to one class); and
* the dividend event is class-aware: a preferred series never inherits the
  issuer's common-stock dividend concepts, and the annual-aggregate concept is
  never shown as a per-share amount.

The view lives in a migration rather than sql/schema.sql: the bootstrap's
raw.dividend_data predates the V0006 ``concept`` column, so a fresh init_db
cannot create a view that reads it. ``test_if_schema_sql_defines_the_view...``
keeps that honest if the two ever converge.
"""

from pathlib import Path

import pytest

VIEW_DDL = "CREATE OR REPLACE VIEW preferred.v_security_terms"
MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"
# The live definition is the newest migration that (re)creates the view.
MIGRATION = max(p for p in MIGRATIONS.glob("V*.sql") if VIEW_DDL in p.read_text())


def _live_connection():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def _sql_body(sql):
    """Strip ``--`` comment lines so prose cannot satisfy or break assertions."""
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _view_statement():
    """Just the CREATE VIEW statement, excluding the trailing COMMENT ON block."""
    for statement in _sql_body(MIGRATION.read_text()).split(";"):
        if "CREATE OR REPLACE VIEW" in statement:
            return statement.lower()
    raise AssertionError("view definition not found in migration")


def _schema_table_block(schema, table):
    """The CREATE TABLE body for ``table`` from schema.sql, braces included."""
    marker = f"CREATE TABLE IF NOT EXISTS {table}"
    start = schema.index(marker)
    end = schema.index(";", start)
    return schema[start:end]


def test_view_is_defined_in_the_migration():
    assert "CREATE OR REPLACE VIEW preferred.v_security_terms" in MIGRATION.read_text()


def test_if_schema_sql_defines_the_view_it_also_has_the_concept_column():
    """The view reads raw.dividend_data.concept, added by V0006.

    It therefore lives only in the migration. If someone later mirrors it into
    the bootstrap, the bootstrap's raw.dividend_data must already carry concept
    or a fresh init_db fails with "column d.concept does not exist".
    """
    schema = (MIGRATION.parent.parent / "schema.sql").read_text()
    if "CREATE OR REPLACE VIEW preferred.v_security_terms" not in schema:
        assert "CREATE OR REPLACE VIEW preferred.v_security_terms" in MIGRATION.read_text()
        return
    assert "concept" in _schema_table_block(schema, "raw.dividend_data")


def test_liquidation_comes_from_per_series_evidence_never_issuer_terms():
    ddl = _view_statement()
    assert "preferred.contract_terms" in ddl
    assert "preferred.security_terms" in ddl
    assert "preferred.issuer_terms" not in ddl, "issuer-level par/aggregate is unallocated"


def test_liquidation_is_range_guarded_and_preferred_only():
    ddl = _view_statement()
    assert "s.security_type = 'preferred stock'" in ddl
    assert "v.value >= 1" in ddl
    assert "v.value <= 1000" in ddl


def test_dividend_pick_is_class_aware():
    ddl = _view_statement()
    # A preferred peeks at the OPENBB true ex-date and its own concept, never the
    # issuer's common declarations.
    assert "d.provider = 'openbb'" in ddl
    assert "d.concept = 'preferredstockdividendspersharedeclared'" in ddl
    # The annual per-share aggregate must not be shown as a per-share amount.
    assert "d.concept = 'commonstockdividendspersharecashpaid' then null" in ddl


def test_dividend_amount_is_guarded():
    assert "(d.amount is null or d.amount <= 1000)" in _view_statement()


def test_the_view_migration_records_the_dividend_feed():
    assert MIGRATION.name == "V0081_dividend_feed_provenance.sql"
    ddl = _view_statement()
    assert "d.feed" in ddl
    assert "dd.feed as dividend_feed" in ddl


def test_view_exposes_a_known_dividend_feed():
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        feeds = set(
            conn.execute(
                text(
                    "SELECT DISTINCT dividend_feed FROM preferred.v_security_terms "
                    "WHERE dividend_provider = 'OPENBB'"
                )
            ).scalars()
        )
    assert feeds, "expected OPENBB-sourced dividends in the view"
    assert feeds <= {"fmp", "yfinance"}


def test_true_ex_dates_rank_first_for_every_security_type():
    """V0066 ranked the SEC common concept (a fiscal period-end) above OPENBB."""
    ddl = _view_statement()
    order_by = ddl[ddl.index("order by\n        case") :]
    assert order_by.index("when d.provider = 'openbb' then 0") < order_by.index(
        "commonstockdividendspersharedeclared"
    )
    assert "when s.security_type = 'preferred stock' and d.provider" not in ddl


def test_preferred_sec_fallback_needs_a_single_active_series():
    ddl = _view_statement()
    assert "ps.active_series = 1" in ddl
    assert "coalesce(d.concept, '') = ''" not in ddl


def _live_engine():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('preferred.v_security_terms') IS NOT NULL")
        ).scalar()
    if not exists:
        pytest.skip("preferred.v_security_terms not applied (run scripts.migrate)")
    return engine


def test_view_has_one_row_per_security():
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        total, distinct = conn.execute(
            text("SELECT count(*), count(DISTINCT security_id) FROM preferred.v_security_terms")
        ).one()
    assert total == distinct


def test_live_liquidation_values_are_in_range_and_per_series():
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        out_of_range, bad_source, non_preferred = conn.execute(
            text("""
            SELECT
              count(*) FILTER (
                WHERE v.liquidation_preference IS NOT NULL
                  AND (v.liquidation_preference < 1 OR v.liquidation_preference > 1000)),
              count(*) FILTER (
                WHERE v.liquidation_source IS NOT NULL
                  AND v.liquidation_source NOT IN
                      ('preferred.contract_terms', 'preferred.security_terms')),
              count(*) FILTER (
                WHERE v.liquidation_preference IS NOT NULL
                  AND s.security_type <> 'preferred stock')
            FROM preferred.v_security_terms v
            JOIN reference.securities s USING (security_id)
            """)
        ).one()
    assert out_of_range == 0
    assert bad_source == 0
    assert non_preferred == 0


def test_live_preferred_dividends_never_use_the_issuer_common_concept():
    """A preferred row from SEC XBRL must carry its own concept (or none).

    OPENBB rows are exempt: they carry a true ex-date and an empty concept, and
    the class filter already refused the issuer common concepts for the rest.
    """
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        leaked = conn.execute(
            text("""
            SELECT count(*)
            FROM preferred.v_security_terms v
            JOIN reference.securities s USING (security_id)
            WHERE s.security_type = 'preferred stock'
              AND v.dividend_concept IS NOT NULL
              AND v.dividend_concept <> ''
              AND v.dividend_concept <> 'PreferredStockDividendsPerShareDeclared'
              AND v.dividend_provider IS DISTINCT FROM 'OPENBB'
            """)
        ).scalar()
        over_guard = conn.execute(
            text("""
            SELECT count(*) FROM preferred.v_security_terms
            WHERE dividend_amount IS NOT NULL AND dividend_amount > 1000
            """)
        ).scalar()
    assert leaked == 0
    assert over_guard == 0


def test_live_sec_period_ends_never_displace_a_stored_true_ex_date():
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        displaced = conn.execute(
            text("""
            SELECT count(*)
            FROM preferred.v_security_terms v
            WHERE v.dividend_provider IS DISTINCT FROM 'OPENBB'
              AND EXISTS (
                SELECT 1 FROM raw.dividend_data d
                WHERE d.security_id = v.security_id AND d.provider = 'OPENBB'
                  AND (d.amount IS NULL OR d.amount <= 1000))
            """)
        ).scalar()
    assert displaced == 0


def test_live_preferred_sec_fallback_is_single_series_only():
    from sqlalchemy import text

    with _live_engine().connect() as conn:
        shared = conn.execute(
            text("""
            SELECT count(*)
            FROM preferred.v_security_terms v
            JOIN reference.securities s USING (security_id)
            WHERE s.security_type = 'preferred stock'
              AND v.dividend_provider = 'SEC_XBRL'
              AND (SELECT count(*) FROM reference.securities o
                   WHERE o.cik = s.cik AND o.active
                     AND o.security_type = 'preferred stock') <> 1
            """)
        ).scalar()
    assert shared == 0
