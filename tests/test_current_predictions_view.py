"""model.current_predictions must be the unambiguous current prediction.

`model.predictions` accumulates a complete set of rows per run, so re-scoring a
date leaves several conflicting sets behind for the same
`(security_id, as_of_date)`. At the latest date two runs currently coexist and
disagree on 5,395 of 5,618 securities, and nothing but `created_at` tells them
apart -- a query without a run filter returns whichever the planner reaches
first, so "the" prediction for a security is arbitrary.

The view exists to stop that question being asked. Two properties matter, and
the second is the one that was got wrong first:

1. For each `(security_id, as_of_date)`, exactly one row, from the newest run
   that has one.
2. Resolution is per **security**, not per **run**. Feature carry-forward means a
   newer run writes only a handful of rows at older dates. A per-run view picks
   the newest run for the date and returns its few carry-forward rows, hiding
   every security it did not happen to touch -- V0043 reported 20 rows for
   2026-10-01 where 5,430 predictions exist.
"""

from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent


def _live_engine():
    pytest.importorskip("sqlalchemy")
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


def test_view_is_created_by_migration_and_declared_in_schema():
    """The view has to exist in a fresh database, not just this one."""
    migrations = list((ROOT / "sql" / "migrations").glob("V004*_current_predictions*.sql"))
    assert migrations, "no migration defines model.current_predictions"
    schema = (ROOT / "sql" / "schema.sql").read_text()
    assert "CREATE OR REPLACE VIEW model.current_predictions" in schema, (
        "schema.sql does not declare the view, so a rebuilt database would lack it"
    )


def test_view_resolves_per_security_not_per_run():
    """Guard the bug V0044 fixed.

    A per-run `DISTINCT ON (as_of_date)` would pass a check that only looks at
    the latest date, where the newest run happens to be the widest. This reads
    the definition and requires the security_id to be the leading key.
    """
    migration = sorted(
        (ROOT / "sql" / "migrations").glob("V004*_current_predictions_per_security*.sql")
    )
    assert migration, "V0044 correction missing"
    body = migration[0].read_text()
    view = body[body.index("CREATE OR REPLACE VIEW") :]
    assert "DISTINCT ON (p.security_id, p.as_of_date)" in view, (
        "the view must resolve per (security_id, as_of_date); resolving per run "
        "drops securities a newer partial run did not cover"
    )


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
class TestCurrentPredictions:
    def _scalar(self, conn, sql, **params):
        return conn.execute(text(sql), params).scalar()

    def test_one_row_per_security_and_date(self):
        """The whole point: no duplicates, so no arbitrary tie-break downstream."""
        conn = _live_engine().connect()
        try:
            dupes = self._scalar(
                conn,
                """
                SELECT count(*) FROM (
                    SELECT security_id, as_of_date FROM model.current_predictions
                    GROUP BY 1, 2 HAVING count(*) > 1) x
                """,
            )
        finally:
            conn.close()
        assert dupes == 0, "a security/date has more than one current prediction"

    def test_every_row_is_the_newest_available_for_its_security_and_date(self):
        """No row in the view may have a newer sibling in the base table."""
        conn = _live_engine().connect()
        try:
            stale = self._scalar(
                conn,
                """
                SELECT count(*) FROM model.current_predictions v
                WHERE EXISTS (
                    SELECT 1 FROM model.predictions p
                    WHERE p.security_id = v.security_id
                      AND p.as_of_date = v.as_of_date
                      AND (p.created_at, p.run_id) > (v.created_at, v.run_id))
                """,
            )
        finally:
            conn.close()
        assert stale == 0, "the view returned a superseded prediction"

    def test_partial_newer_run_does_not_hide_older_predictions(self):
        """The carry-forward case V0043 got wrong.

        At least one date exists where the newest run covers only part of it. If
        the view resolved per run, that date would collapse to the newer run's
        handful of rows instead of the full coverage beneath it.
        """
        conn = _live_engine().connect()
        try:
            partial = self._scalar(
                conn,
                """
                SELECT count(*) FROM (
                    SELECT as_of_date FROM model.predictions
                    GROUP BY as_of_date
                    HAVING count(DISTINCT run_id) > 1) x
                """,
            )
            if partial == 0:
                pytest.skip("no date has coexisting runs to distinguish")
            lost = self._scalar(
                conn,
                """
                SELECT count(*) FROM (
                    SELECT as_of_date,
                           count(DISTINCT security_id) AS covered
                    FROM model.predictions GROUP BY 1) widest
                JOIN (
                    SELECT as_of_date, count(*) AS kept
                    FROM model.current_predictions GROUP BY 1) v
                  USING (as_of_date)
                WHERE v.kept < widest.covered
                """,
            )
        finally:
            conn.close()
        assert lost == 0, (
            "the view holds fewer predictions than some single run wrote for a "
            "date; a newer partial run is shadowing the run beneath it"
        )

    def test_view_agrees_with_scores_coverage(self):
        """Per-date counts should line up with model.scores for the same date."""
        conn = _live_engine().connect()
        try:
            matching, total = conn.execute(
                text(
                    """
                    SELECT count(*) FILTER (WHERE v.n = s.n), count(*)
                    FROM (SELECT as_of_date, count(*) n FROM model.current_predictions GROUP BY 1) v
                    JOIN (SELECT as_of_date, count(*) n FROM model.scores GROUP BY 1) s
                      USING (as_of_date)
                    """
                )
            ).one()
        finally:
            conn.close()
        assert total > 0, "no dates in common to compare"
        assert matching == total, (
            f"current_predictions and scores disagree on coverage for "
            f"{total - matching} of {total} dates"
        )

    def test_base_table_is_retained_as_the_audit_trail(self):
        """The view must not have been bought by deleting superseded runs."""
        conn = _live_engine().connect()
        try:
            total_runs = self._scalar(conn, "SELECT count(DISTINCT run_id) FROM model.predictions")
            view_runs = self._scalar(
                conn, "SELECT count(DISTINCT run_id) FROM model.current_predictions"
            )
        finally:
            conn.close()
        assert total_runs > view_runs, (
            "model.predictions no longer holds runs the view omits, so the audit "
            "trail is gone; pruning is a separate retention decision"
        )
