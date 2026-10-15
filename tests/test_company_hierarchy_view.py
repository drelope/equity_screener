"""clean.v_company_hierarchy must be one row per issuer, never per listing.

The hierarchy is a JOIN shape (primary listing -> sibling listings, officers,
per-listing corporate actions), so it is exposed as a view rather than new
columns. These tests pin the invariants that keep it a hierarchy instead of a
fan-out:

  * the primary-listing rule (1 = the symbol with no '-'/'.' postfix, else the
    shortest) must be applied at (cik) granularity only -- partitioning on the
    profile_id surrogate would leave every listing "primary" and multiply the
    children array per row;
  * exactly one child per issuer carries is_primary_listing = true and its
    symbol must equal the parent's primary_symbol;
  * count(*) == count(distinct cik) at all times;
  * children keep their own per-listing quote/valuation/dividend values and
    carry security_type (reference.securities), while only issuer-level keys
    and lineage are stripped;
  * varying_parent_attributes reports issuer_key drift only -- quote/valuation
    keys legitimately differ per listing and must never be reported.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V0060 = ROOT / "sql" / "migrations" / "V0060_company_hierarchy_view.sql"
V0061 = ROOT / "sql" / "migrations" / "V0061_company_hierarchy_refinements.sql"
MIGRATION = V0061


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
    """Just the CREATE VIEW statement, excluding the COMMENT ON block after it."""
    for statement in _sql_body(MIGRATION.read_text()).split(";"):
        if "CREATE OR REPLACE VIEW" in statement:
            return statement.lower()
    raise AssertionError("view definition not found in migration")


def test_view_is_defined_in_the_migrations():
    assert "CREATE OR REPLACE VIEW clean.v_company_hierarchy" in V0060.read_text()
    assert "CREATE OR REPLACE VIEW clean.v_company_hierarchy" in V0061.read_text()


def test_view_is_migration_only_and_not_in_schema_sql():
    """The view deliberately lives only in V0060/V0061, following the V0055
    clean.corporate_action precedent: it depends on clean.corporate_action,
    which sql/schema.sql does not create (V0055 added the table and its view
    via migration). Declaring the view in schema.sql would make the drift
    check's reference build fail at the schema.sql-only step, since the view
    would reference a table that does not exist yet there. Migrations complete
    the picture: check_schema_drift applies schema.sql, then init_db's inline
    migrations, then every V#### file in order."""
    schema = (ROOT / "sql" / "schema.sql").read_text()
    assert "clean.v_company_hierarchy" not in schema


def test_view_is_read_only():
    ddl = _view_statement()
    assert "insert" not in ddl
    assert "update " not in ddl
    assert "delete" not in ddl


def test_view_reads_only_clean_profile_tables_and_reference_securities():
    ddl = _view_statement()
    assert "clean.company_profile" in ddl
    assert "clean.company_officer" in ddl
    assert "clean.corporate_action" in ddl
    assert "reference.securities" in ddl, "children carry security_type via reference"
    assert "raw." not in ddl


def test_primary_listing_is_partitioned_by_cik_only():
    """If profile_id were in the PARTITION BY, every row would get listing_rank
    1 and the parent join would fan each issuer's children out by its number of
    listings. The partition must be the issuer key (cik) alone."""
    ddl = _view_statement()
    assert "partition by cp.cik" in ddl
    assert "cp.cik, cp.issuer_id, cp.profile_id" not in ddl


def test_join_keys_are_cik_not_issuer_id_or_profile_id():
    """company_profile.issuer_id is a reference.issuers key, not a profile_id;
    joining on issuer_id = parent.profile_id matches nothing (verified: 0 rows
    in the live database). The hierarchy must be keyed on cik."""
    ddl = _view_statement()
    assert "child.issuer_id = parent.profile_id" not in ddl
    assert "on c.cik = par.cik" in ddl, "parent/children must be keyed on cik"
    assert "on po.cik = par.cik" in ddl
    assert "on pc.cik = par.cik" in ddl


def test_view_rows_are_one_per_issuer_in_the_live_database():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        total, distinct_cik, bad_primary, bad_children = conn.execute(
            text("""
            SELECT count(*),
                   count(DISTINCT cik),
                   count(*) FILTER (WHERE primary_symbol IS NULL OR primary_symbol = ''),
                   count(*) FILTER (WHERE child_count IS NULL OR child_count < 1)
            FROM clean.v_company_hierarchy
            """)
        ).one()

    assert total == distinct_cik, "count(*) must equal count(distinct cik): no fan-out"
    assert bad_primary == 0, "every issuer must have a primary_symbol"
    assert bad_children == 0, "every issuer must list at least one child"
    assert total > 0


def test_exactly_one_primary_child_matching_primary_symbol():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        bad_primary, primary_count, issuers = conn.execute(
            text("""
            SELECT count(*) FILTER (
                       WHERE j->>'is_primary_listing' = 'true'
                         AND j->>'symbol' IS DISTINCT FROM h.primary_symbol),
                   count(*) FILTER (WHERE j->>'is_primary_listing' = 'true'),
                   count(DISTINCT h.cik)
            FROM clean.v_company_hierarchy h
            CROSS JOIN LATERAL jsonb_array_elements(h.children) j
            """)
        ).one()

    assert bad_primary == 0, "a child marked primary must equal the issuer's primary_symbol"
    assert primary_count == issuers, "exactly one primary child per issuer"


def test_children_are_ordered_primary_first_then_symbol():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        first_symbols = conn.execute(
            text("""
            SELECT jsonb_array_length(children),
                   children->0->>'is_primary_listing',
                   children->0->>'symbol'
            FROM clean.v_company_hierarchy
            WHERE cik = '0001253986'
            """)
        ).first()

    assert first_symbols is not None
    length, is_primary, symbol = first_symbols
    assert length == 4, "ABR has four listings"
    assert is_primary == "true" and symbol == "ABR", "primary listing must come first"


def test_children_carry_security_type_and_keep_their_own_quote_values():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        with_type, without_type, with_market_cap, with_city = conn.execute(
            text("""
            SELECT count(*) FILTER (WHERE j->>'security_type' IS NOT NULL),
                   count(*) FILTER (WHERE NOT j ? 'security_type'),
                   count(*) FILTER (WHERE j ? 'market_cap'),
                   count(*) FILTER (WHERE j ? 'city')
            FROM clean.v_company_hierarchy h
            CROSS JOIN LATERAL jsonb_array_elements(h.children) j
            """)
        ).one()

    assert without_type == 0, "every child must carry a security_type key"
    assert with_type > 0, "children should resolve security_type from reference.securities"
    assert with_market_cap > 0, "children must keep their own per-listing quote values"
    assert with_city == 0, "issuer-level keys must be stripped from children, not overridden"


def test_varying_parent_attributes_is_issuer_key_drift_only():
    """quote/valuation keys (market_cap, eps_forward, regular_market_time, ...)
    legitimately differ per listing and must never be reported as conflicts."""
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        quote_key_issuers = conn.execute(
            text("""
            SELECT count(DISTINCT h.cik)
            FROM clean.v_company_hierarchy h,
                 LATERAL unnest(coalesce(h.varying_parent_attributes, '{}'::text[])) k(key)
            WHERE k.key IN
                ('market_cap', 'regular_market_time', 'trailing_eps', 'eps_forward',
                 'forward_eps', 'forward_p_e', 'payout_ratio', 'target_low_price',
                 'eps_current_year', 'audit_risk', 'board_risk')
            """)
        ).scalar()

    assert quote_key_issuers == 0, "quote/valuation keys must never appear as issuer drift"


def test_parent_exposes_primary_security_type_and_issue_type_label():
    pytest.importorskip("sqlalchemy")
    engine = _live_connection()
    if engine is None:
        pytest.skip("no database available")
    from sqlalchemy import text

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('clean.v_company_hierarchy') IS NOT NULL")
        ).scalar()
        if not exists:
            pytest.skip("clean.v_company_hierarchy not applied (run python -m scripts.migrate)")

        cols = {
            row[0]
            for row in conn.execute(
                text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'clean' AND table_name = 'v_company_hierarchy'
                """)
            )
        }

    assert "issue_type_label" in cols, "the generic 'type' alias must be renamed"
    assert "type" not in cols
    assert "security_type" in cols, "parent must expose the primary listing's security_type"
    assert "varying_parent_attributes" in cols
    assert "children" in cols
