"""Stale same-date score rows must not survive a scoring run.

`model.scores` and `model.rankings` are keyed by (security_id, as_of_date) and
carry no run_id, so the upsert in score_rank refreshes the rows it writes and
leaves every other row at that date untouched. A security that fell out of the
scoring frame -- deactivated, or it lost its features -- kept its old
composite_score and still looked scoreable downstream.

`model.predictions` never had this problem because it is keyed by run_id and
already had a prune step; these two tables did not.

The invariant the prune protects is narrow on purpose: the *run date* is
rebuilt, earlier dates are point-in-time history and are never touched. A re-run
that reached back and deleted old dates would destroy the record of what a
security scored on the day it actually scored.
"""

from contextlib import contextmanager
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


def _scalar(conn, sql, **params):
    return conn.execute(text(sql), params).scalar()


def test_prune_is_scoped_to_the_run_date():
    """Guard the source against the failure mode of reaching back in time."""
    source = (ROOT / "scripts" / "score_rank.py").read_text()
    body = source[source.index("def prune_stale_run_rows") : source.index("def main(")]
    assert "as_of_date = :d" in body
    # The only date the DELETE may reference is the run date passed in; it must
    # not resolve a date of its own.
    assert "current_date" not in body.replace(":d", "")


def test_prune_targets_both_scores_and_rankings():
    """Predictions were already pruned by run_id; these two were the gap."""
    source = (ROOT / "scripts" / "score_rank.py").read_text()
    body = source[source.index("def prune_stale_run_rows") : source.index("def main(")]
    assert '"scores"' in body and '"rankings"' in body


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
class TestPruneRemovesStaleRows:
    @staticmethod
    @contextmanager
    def _rolled_back_conn():
        """Yield a connection whose transaction is *always* rolled back.

        These tests delete real rows on purpose, so they must not be able to
        commit even when every assertion passes. An earlier version used
        ``engine.begin()``, which commits on normal exit: the DELETE fired, the
        assertions passed, and a green test run destroyed 5,617 published score
        and ranking rows at the run date. Rolling back in a finally block makes
        the destructive step safe regardless of how the test ends.
        """
        conn = _live_engine().connect()
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
            conn.close()

    def test_stale_row_at_run_date_is_removed_and_kept_rows_survive(self):
        from scripts.score_rank import prune_stale_run_rows

        with self._rolled_back_conn() as conn:
            run_date = _scalar(conn, "SELECT max(as_of_date) FROM model.scores")
            if run_date is None:
                pytest.skip("no scores to test against")

            # The full set this run is assumed to write: every security that
            # already has a row at the run date. Passing a partial set would
            # (correctly) prune the rest of the date.
            scored_sids = [
                r[0]
                for r in conn.execute(
                    text("SELECT security_id FROM model.scores WHERE as_of_date = :d"),
                    {"d": run_date},
                ).all()
            ]
            n_kept = _scalar(
                conn,
                "SELECT count(*) FROM model.scores WHERE as_of_date = :d",
                d=run_date,
            )
            n_ranked = _scalar(
                conn,
                "SELECT count(*) FROM model.rankings WHERE as_of_date = :d",
                d=run_date,
            )

            # Stands in for a security that fell out of the frame: one with no
            # score row at the run date.
            victim = _scalar(
                conn,
                """
                SELECT s.security_id FROM reference.securities s
                WHERE NOT EXISTS (
                    SELECT 1 FROM model.scores x
                    WHERE x.security_id = s.security_id AND x.as_of_date = :d)
                LIMIT 1
                """,
                d=run_date,
            )
            if victim is None:
                pytest.skip("every security already has a score at the run date")

            conn.execute(
                text(
                    """
                    INSERT INTO model.scores
                    (security_id, as_of_date, composite_score, score_coverage)
                    VALUES (:sid, :d, 0.99, 1.0)
                    """
                ),
                {"sid": victim, "d": run_date},
            )
            assert (
                _scalar(
                    conn,
                    "SELECT count(*) FROM model.scores WHERE as_of_date = :d",
                    d=run_date,
                )
                == n_kept + 1
            )

            pruned = prune_stale_run_rows(conn, run_date, scored_sids)

            assert pruned["scores"] == 1, "the stale same-date score survived"
            assert (
                _scalar(
                    conn,
                    "SELECT count(*) FROM model.scores WHERE as_of_date = :d",
                    d=run_date,
                )
                == n_kept
            )
            assert (
                _scalar(
                    conn,
                    "SELECT count(*) FROM model.rankings WHERE as_of_date = :d",
                    d=run_date,
                )
                == n_ranked
            )

    def test_earlier_dates_are_untouched(self):
        """Point-in-time history must survive a prune of a later run date."""
        from scripts.score_rank import prune_stale_run_rows

        with self._rolled_back_conn() as conn:
            newest = _scalar(conn, "SELECT max(as_of_date) FROM model.scores")
            earlier = _scalar(
                conn,
                """
                SELECT max(as_of_date) FROM model.scores
                WHERE as_of_date < (SELECT max(as_of_date) FROM model.scores)
                """,
            )
            if earlier is None:
                pytest.skip("only one scored date present")

            before = _scalar(
                conn,
                "SELECT count(*) FROM model.scores WHERE as_of_date = :d",
                d=earlier,
            )
            scored_sids = [
                r[0]
                for r in conn.execute(
                    text("SELECT security_id FROM model.scores WHERE as_of_date = :d"),
                    {"d": newest},
                ).all()
            ]

            prune_stale_run_rows(conn, newest, scored_sids)

            after = _scalar(
                conn,
                "SELECT count(*) FROM model.scores WHERE as_of_date = :d",
                d=earlier,
            )
        assert before == after, "pruning the newest date reached back and deleted history"
