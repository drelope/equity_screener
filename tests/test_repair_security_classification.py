"""The classification repair: decisive evidence only, and reversible by re-run.

The repair moves SPAC warrants/rights/units stored as ``preferred stock`` to the
type the SEC symbol/title proves, clears issuer-name-parse terms that leaked onto
common stock, and drops implausible preferred dividend rates. These tests pin the
safety rails -- the ambiguous hyphenless ``...W``/``...R`` needs a base sibling,
``...PR`` series are never touched, only active preferred rows are in scope, and a
row that already has a twin of the target type is left alone -- then exercise the
SQL against seeded rows in a transaction that is always rolled back.
"""

import pytest
from sqlalchemy import text

from scripts import repair_security_classification as repair

# --- SQL shape: safety rails that must not silently disappear -----------------


def test_only_active_preferred_rows_are_candidates():
    sql = repair.RECLASSIFY_SQL
    assert "s.active AND s.security_type = 'preferred stock'" in sql


def test_hyphenless_candidates_require_a_base_sibling_unless_a_title_says_so():
    sql = repair.RECLASSIFY_SQL
    # The gate exists and is bound to the base symbol within the same CIK...
    assert "UPPER(b.ticker) = UPPER(c.base)" in sql
    # ...but a decisive dei title bypasses it (a title is evidence on its own).
    assert "title_type IS NOT NULL AS from_title" in sql
    assert "c.from_title" in sql


def test_pr_suffix_is_excluded_from_the_hyphenless_r_rule():
    assert "s.ticker !~ 'PR$'" in repair.RECLASSIFY_SQL


def test_a_row_with_an_existing_twin_of_the_target_type_is_skipped():
    assert "d.security_type = c.new_type AND d.dividend = c.dividend" in repair.RECLASSIFY_SQL
    assert "d.security_id <> c.security_id" in repair.RECLASSIFY_SQL


def test_common_leak_clears_only_common_rows():
    sql = repair.CLEAR_COMMON_LEAK_SQL
    assert "security_type = 'common_stock'" in sql
    assert "coupon_rate = NULL" in sql and "liquidation_preference = NULL" in sql


def test_absurd_rate_bounds_are_exclusive():
    sql = repair.CLEAR_ABSURD_RATE_SQL
    assert "dividend_rate < 0.01 OR dividend_rate > 1000" in sql


# --- live behaviour: seeded rows in a rolled-back transaction -----------------


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def _insert_company_ticker(conn, ticker, cik):
    conn.execute(
        text("""
        INSERT INTO raw.company_ticker (ticker, cik, title, raw_payload)
        VALUES (:ticker, :cik, :title, '{}'::jsonb)
        ON CONFLICT (ticker) DO NOTHING
        """),
        {"ticker": ticker, "cik": cik, "title": f"{ticker} test issuer"},
    )


def _insert_security(
    conn, ticker, cik, security_type, *, dividend=False, coupon=None, liquidation=None
):
    _insert_company_ticker(conn, ticker, cik)
    return conn.execute(
        text("""
        INSERT INTO reference.securities
            (ticker, cik, security_id, security_name, security_type, dividend,
             coupon_rate, liquidation_preference, active)
        VALUES (:ticker, :cik, gen_random_uuid(), :name, :type, :dividend,
                :coupon, :liquidation, TRUE)
        RETURNING security_id
        """),
        {
            "ticker": ticker,
            "cik": cik,
            "name": f"{ticker} test instrument",
            "type": security_type,
            "dividend": dividend,
            "coupon": coupon,
            "liquidation": liquidation,
        },
    ).scalar_one()


def _insert_title(conn, cik, ticker, title):
    conn.execute(
        text("""
        INSERT INTO raw.sec_instrument_titles (cik, ticker, title, content_hash)
        VALUES (:cik, :ticker, :title, 'test')
        ON CONFLICT (cik, ticker) DO UPDATE SET title = EXCLUDED.title
        """),
        {"cik": cik, "ticker": ticker, "title": title},
    )


def test_seeded_reclassification_and_clearing_round_trip():
    engine = _live_engine()
    if engine is None:
        pytest.skip("no database available")

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # CIK 1: a hyphenless warrant and right with their base sibling present.
            _insert_security(conn, "ZQA", "9000000001", "common_stock")
            _insert_security(conn, "ZQAW", "9000000001", "preferred stock")
            _insert_security(conn, "ZQAR", "9000000001", "preferred stock")
            # CIK 1: a ...PR series that must never be read as a right.
            _insert_security(conn, "ZQAP", "9000000001", "common_stock")
            _insert_security(conn, "ZQAPR", "9000000001", "preferred stock")

            # CIK 2: hyphenless W/R with no base sibling are ambiguous, left alone;
            # a dashed -U unit is decisive.
            _insert_security(conn, "ZQBW", "9000000002", "preferred stock")
            _insert_security(conn, "ZQBR", "9000000002", "preferred stock")
            _insert_security(conn, "ZQB-U", "9000000002", "preferred stock")

            # CIK 3: a dei title is decisive even without a suffix or a base.
            _insert_security(conn, "ZQCX", "9000000003", "preferred stock")
            _insert_title(conn, "9000000003", "ZQCZ", "ZQCZ Warrant to purchase common stock")
            _insert_security(conn, "ZQCZ", "9000000003", "preferred stock")

            # CIK 4: a common row carrying issuer-name-parse preferred terms.
            _insert_security(conn, "ZQL", "9000000004", "common_stock", coupon=8.5, liquidation=25)
            # CIK 4: an implausible preferred rate and a plausible one.
            bad = _insert_security(conn, "ZQP", "9000000004", "preferred stock")
            good = _insert_security(conn, "ZQQ", "9000000004", "preferred stock")
            conn.execute(
                text("""
                INSERT INTO preferred.security_terms (security_id, dividend_rate)
                VALUES (:bad, 33500000), (:good, 7.875)
                """),
                {"bad": bad, "good": good},
            )

            rows, summary = repair.repair(conn)
            by_ticker = dict(rows)
            changed = set(by_ticker)

            assert by_ticker["ZQAW"] == "derivative"
            assert by_ticker["ZQAR"] == "derivative"
            assert by_ticker["ZQB-U"] == "other_debt_and_equity"
            assert by_ticker["ZQCZ"] == "derivative"  # dei title, no base needed
            assert "ZQAPR" not in changed  # ...PR is not a right
            assert "ZQBW" not in changed and "ZQBR" not in changed  # no base sibling
            assert "ZQCD" not in changed

            leak, rate = conn.execute(
                text("""
                SELECT
                  (SELECT coupon_rate FROM reference.securities WHERE ticker = 'ZQL'),
                  (SELECT dividend_rate FROM preferred.security_terms
                    WHERE security_id = :bad)
                """),
                {"bad": bad},
            ).one()
            assert leak is None
            good_rate = conn.execute(
                text("SELECT dividend_rate FROM preferred.security_terms WHERE security_id = :g"),
                {"g": good},
            ).scalar_one()
            assert float(good_rate) == 7.875
            assert summary["reclassified"] >= 4
            assert summary["cleared_common_leak"] >= 1
            assert summary["cleared_absurd_rate"] >= 1
        finally:
            trans.rollback()


def test_repair_is_idempotent():
    engine = _live_engine()
    if engine is None:
        pytest.skip("no database available")

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            _insert_security(conn, "ZQA", "9000000011", "common_stock")
            _insert_security(conn, "ZQAW", "9000000011", "preferred stock")

            first, _ = repair.repair(conn)
            second, _ = repair.repair(conn)

            assert "ZQAW" in dict(first)
            # The second pass re-runs the UPDATE, but its RETURNING yields nothing
            # because the row is already the target type.
            assert "ZQAW" not in dict(second)
        finally:
            trans.rollback()
