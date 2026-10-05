"""Carry-forward must widen the read window without reintroducing the common-date rule.

model.features has one row per real observation date, so a security that did not
trade on the run date has no row for it. Reading only MAX(as_of_date) dropped
155 active dividend payers out of the 2026-10-02 composite, 78 of them a single
trading day stale.

The text assertions pin the invariant that the window is parameterised and scoped
per security: the regression that matters is a consumer quietly reverting to one
global date, and that is visible in the query rather than in any one run's row
count. The live tests then execute the real builder to confirm the text is also
valid SQL and does what it claims.
"""

import inspect

import pytest

from scripts import score_rank
from src.crispdm import feature_window as fw


def _flat(sql):
    """Collapse whitespace and spacing around operators so assertions do not
    depend on how the SQL happens to be wrapped in the source."""
    flat = " ".join(sql.split())
    for op in ("<=", ">=", "!=", "<", ">", "="):
        flat = flat.replace(f" {op} ", op)
    return flat


CONSUMERS = [
    pytest.param(fw.scoring_features_sql, id="scoring"),
    pytest.param(lambda: fw.dashboard_features_sql("f.current_price"), id="dashboard"),
]


class TestConfigDefault:
    def test_default_tolerance_is_seven_days(self):
        assert fw.carry_forward_days() == 7

    def test_tolerance_is_configurable(self, monkeypatch):
        from src.crispdm.config import settings

        monkeypatch.setattr(settings, "feature_carry_forward_days", 30, raising=False)
        assert fw.carry_forward_days() == 30

    def test_zero_is_the_documented_opt_out(self, monkeypatch):
        from src.crispdm.config import settings

        monkeypatch.setattr(settings, "feature_carry_forward_days", 0, raising=False)
        assert fw.carry_forward_days() == 0


@pytest.mark.parametrize("sql_fn", CONSUMERS)
class TestBothConsumersShareTheWindow:
    def test_never_requires_a_single_global_as_of_date(self, sql_fn):
        flat = _flat(sql_fn())
        assert "WHERE f.as_of_date=(SELECT MAX(as_of_date) FROM model.features)" not in flat
        assert "WHERE g.as_of_date=(SELECT MAX(as_of_date) FROM model.features)" not in flat

    def test_window_is_bound_not_interpolated(self, sql_fn):
        assert ":carry_days" in _flat(sql_fn())

    def test_upper_bound_is_still_the_latest_feature_date(self, sql_fn):
        """Carry forward from the past only; never admit a future-dated row."""
        flat = _flat(sql_fn())
        assert "g.as_of_date<=(SELECT MAX(as_of_date) FROM model.features)" in flat

    def test_lower_bound_is_the_tolerance(self, sql_fn):
        assert "- make_interval(days => :carry_days)" in _flat(sql_fn())

    def test_reads_the_latest_row_per_security(self, sql_fn):
        flat = _flat(sql_fn())
        assert "g.security_id=" in flat
        assert "ORDER BY g.as_of_date DESC LIMIT 1" in flat

    def test_does_not_correlate_max_over_the_feature_table(self, sql_fn):
        """Guard the 28s plan.

        Expressing the window as `f.as_of_date = (SELECT MAX(g.as_of_date) ...
        WHERE g.security_id = f.security_id)` looks equivalent but gets
        de-correlated into a join across every feature row: 8.5M subquery
        evaluations, 28s, 42.7M buffer hits. The LATERAL + ORDER BY/LIMIT 1 shape
        is one index probe per security and runs in ~54ms.
        """
        flat = _flat(sql_fn())
        assert "MAX(g.as_of_date) FROM model.features g" not in flat

    def test_drives_off_the_securities_table(self, sql_fn):
        """The row count must scale with the security list, not the feature table."""
        flat = _flat(sql_fn())
        assert "FROM reference.securities s" in flat
        assert "JOIN LATERAL" in flat

    def test_excludes_inactive_securities(self, sql_fn):
        assert "s.active=TRUE" in _flat(sql_fn())


class TestScoringQuery:
    def test_returns_feature_columns_plus_ticker_and_type(self):
        flat = _flat(fw.scoring_features_sql())
        assert flat.startswith("SELECT f.*, s.ticker, s.security_type")

    def test_scope_is_the_active_securities_only(self):
        assert "WHERE s.active=TRUE" in _flat(fw.scoring_features_sql())


class TestDashboardQuery:
    def test_scores_join_on_the_carried_rows_own_date(self):
        """Joining on the run date instead would silently drop carried rows."""
        flat = _flat(fw.dashboard_features_sql("f.current_price"))
        assert "sc.security_id=f.security_id AND sc.as_of_date=f.as_of_date" in flat

    def test_keeps_score_sort_order(self):
        assert "ORDER BY sc.composite_score DESC NULLS LAST" in _flat(
            fw.dashboard_features_sql("f.current_price")
        )

    def test_includes_requested_columns(self):
        assert "f.current_price" in _flat(fw.dashboard_features_sql("f.current_price"))


def _live_engine():
    pytest.importorskip("sqlalchemy")
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return engine
    except Exception:  # pragma: no cover - environments without a database
        return None


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
class TestLiveWindow:
    """Runs the real query text, not a hand-copied approximation of it."""

    def _run(self, sql, days=None):
        """Substitute :carry_days inline.

        exec_driver_sql hands the string to psycopg untouched, so SQLAlchemy's
        :name -> $n translation never happens and Postgres would see a literal
        colon. The value is an int from config, so formatting it in is safe.
        """
        engine = _live_engine()
        value = fw.carry_forward_days() if days is None else days
        assert isinstance(value, int), f"tolerance must interpolate as an int: {value!r}"
        with engine.connect() as conn:
            return conn.exec_driver_sql(sql.replace(":carry_days", str(value))).all()

    def test_scoring_sql_is_valid_and_returns_one_row_per_security(self):
        # Project two columns rather than *: the window is the subject here, and
        # dragging every feature column through 5.7k rows dominates the runtime.
        rows = self._run(f"SELECT security_id, as_of_date FROM ({fw.scoring_features_sql()}) t")
        assert rows, "query returned nothing; the fixture is empty"
        ids = [r.security_id for r in rows]
        assert len(ids) == len(set(ids)), "window fanned out: duplicate securities"

    def test_dashboard_sql_is_valid(self):
        rows = self._run(
            fw.dashboard_features_sql("f.current_price,f.dividend_yield,f.volatility_252d")
        )
        assert rows, "query returned nothing; the fixture is empty"

    def test_default_tolerance_widens_the_universe(self):
        strict = self._run(f"SELECT count(*) AS n FROM ({fw.scoring_features_sql()}) t", days=0)[
            0
        ].n
        windowed = self._run(f"SELECT count(*) AS n FROM ({fw.scoring_features_sql()}) t")[0].n
        assert windowed > strict, (
            f"carry-forward did not widen the universe: {windowed} vs {strict}"
        )

    def test_no_inactive_security_is_read(self):
        rows = self._run(
            f"""SELECT count(*) AS n FROM ({fw.scoring_features_sql()}) t
                JOIN reference.securities s USING (security_id)
                WHERE NOT s.active"""
        )
        assert rows[0].n == 0

    def test_no_row_older_than_the_window_is_read(self):
        days = fw.carry_forward_days()
        rows = self._run(
            f"""SELECT count(*) AS n FROM ({fw.scoring_features_sql()}) t
                WHERE t.as_of_date < (SELECT MAX(as_of_date) FROM model.features)
                                       - make_interval(days => {days})"""
        )
        assert rows[0].n == 0


class TestRunDateIsNotTakenFromTheFirstRow:
    """score_rank must date the run by the newest row, not by whichever is first.

    Before carry-forward every row in the frame shared one as_of_date, so
    iloc[0] was a safe way to name the run. With mixed dates it is arbitrary, and
    a carried-forward row landing first would file the entire run -- and every
    score in it -- under a stale date.
    """

    def test_as_of_comes_from_the_maximum(self):
        source = inspect.getsource(score_rank)
        assert 'as_of = x["as_of_date"].max()' in source

    def test_first_row_is_not_used_as_the_run_date(self):
        source = inspect.getsource(score_rank)
        assert 'as_of = x["as_of_date"].iloc[0]' not in source
        assert "x['as_of_date'].iloc[0]" not in source
