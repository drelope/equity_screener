"""Quarantine must be inert, reversible, and honest about why.

The five future `dividend_last_paid` values are left in place rather than
NULLed or deleted, because deleting them would hide a real matcher defect and
destroy the evidence needed to verify the fix. That is only safe while two things
hold, and both are easy to break silently:

1. Nothing in the composite path reads the column. If a future feature starts
   reading it, a date in 2108 would reach a published score and the "inert"
   justification becomes false.
2. The registry stays in sync with reality. A quarantined row that has since
   been fixed must not still read as an open finding, and a new anomaly must not
   appear without a registry entry.
"""

from pathlib import Path

import pytest

from src.crispdm.config import settings

#: The modules that produce model.features and the composite score. A
#: dividend_last_paid reference anywhere in these is what would make the
#: quarantine unsafe.
COMPOSITE_PATH = [
    "features.py",
    "scoring.py",
    "model.py",
    "regime.py",
    "regime_pipeline.py",
]

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


class TestColumnCannotReachTheComposite:
    @pytest.mark.parametrize("module", COMPOSITE_PATH)
    def test_composite_path_never_reads_dividend_last_paid(self, module):
        """The whole safety argument rests on this. Keep it true."""
        source = (ROOT / "src" / "crispdm" / module).read_text()
        assert "dividend_last_paid" not in source, (
            f"{module} references dividend_last_paid; the five quarantined "
            "future dates would now reach a published score"
        )

    def test_build_features_reads_raw_tables_not_the_reference_layer(self):
        source = (ROOT / "src" / "crispdm" / "features.py").read_text()
        assert "raw.market_data" in source
        assert "raw.dividend_data" in source


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
class TestRegistryTracksReality:
    def _conn(self):
        return _live_engine().connect()

    def test_every_live_anomaly_has_a_registry_entry(self):
        """A new future-dated value must not appear unrecorded."""
        with self._conn() as conn:
            missing = conn.exec_driver_sql(
                """
                SELECT count(*) FROM reference.securities s
                WHERE s.dividend_last_paid > now()::date
                  AND NOT EXISTS (
                        SELECT 1 FROM audit.quarantined_values q
                        WHERE q.row_key = s.security_id::text
                          AND q.column_name = 'dividend_last_paid'
                          AND q.resolved_at IS NULL)
                """
            ).scalar()
        assert missing == 0, f"{missing} live anomal(y/ies) not in the registry"

    def test_no_entry_stays_open_after_being_fixed(self):
        """Conversely, a resolved value must not keep reading as a finding."""
        with self._conn() as conn:
            stale = conn.exec_driver_sql(
                """
                SELECT count(*) FROM audit.quarantined_values q
                WHERE q.resolved_at IS NULL
                  AND q.column_name = 'dividend_last_paid'
                  AND NOT EXISTS (
                        SELECT 1 FROM reference.securities s
                        WHERE s.security_id::text = q.row_key
                          AND s.dividend_last_paid::text = q.observed_value
                          AND s.dividend_last_paid > now()::date)
                """
            ).scalar()
        assert stale == 0, f"{stale} registry entr(y/ies) no longer anomalous"

    def test_quarantined_value_is_left_in_place(self):
        """The core invariant: quarantine parks a value, it does not remove it.

        A NULLed or deleted value would satisfy the anomaly checks above by
        erasing the evidence, and the next matcher fix would have nothing to
        compare against.
        """
        with self._conn() as conn:
            erased = conn.exec_driver_sql(
                """
                SELECT count(*) FROM audit.quarantined_values q
                WHERE q.resolved_at IS NULL
                  AND NOT EXISTS (
                        SELECT 1 FROM reference.securities s
                        WHERE s.security_id::text = q.row_key
                          AND s.dividend_last_paid::text = q.observed_value)
                """
            ).scalar()
        assert erased == 0, "a quarantined value was deleted or overwritten"

    def test_quarantined_securities_still_hold_their_own_rows(self):
        """Quarantine excludes a value from use, not a security from the universe.

        All five are published. Excluding the securities to suppress a bad date
        would silently shrink the scored universe, which is the thing this whole
        exercise has been avoiding.

        The registry keeps resolved rows (resolution is recorded by stamping
        resolved_at, never by deleting), so this deliberately ignores resolved_at:
        the guarantee is about the *security*, and it has to keep holding after
        the value it referred to was corrected. Filtering on
        "still unresolved" here would make the test pass vacuously once V0040
        resolved all five, which is exactly when the guarantee still matters.
        """
        with self._conn() as conn:
            active = conn.exec_driver_sql(
                """
                SELECT count(*) FROM audit.quarantined_values q
                JOIN reference.securities s ON s.security_id::text = q.row_key
                WHERE s.active
                """
            ).scalar()
        assert active > 0, "quarantine deactivated the securities instead"

    def test_resolved_quarantine_rows_still_have_their_security_published(self):
        """Resolving a quarantined value must not have deactivated its security.

        V0040 clamped the five future dividend_last_paid values to today and
        stamped resolved_at. The correction was supposed to touch the value
        only; the securities stay in the scored universe.
        """
        with self._conn() as conn:
            row = (
                conn.exec_driver_sql(
                    """
                SELECT
                    count(*) FILTER (WHERE q.resolved_at IS NOT NULL) AS resolved,
                    count(*) FILTER (
                        WHERE q.resolved_at IS NOT NULL AND s.active
                    ) AS resolved_still_active,
                    count(*) FILTER (
                        WHERE q.resolved_at IS NOT NULL
                          AND s.dividend_last_paid <= current_date
                    ) AS resolved_value_now_valid
                FROM audit.quarantined_values q
                JOIN reference.securities s ON s.security_id::text = q.row_key
                WHERE q.column_name = 'dividend_last_paid'
                """
                )
                .mappings()
                .one()
            )
        assert row["resolved"] > 0, "expected at least one resolved quarantine row"
        assert row["resolved_still_active"] == row["resolved"], (
            "resolving a quarantined value must not deactivate its security"
        )
        assert row["resolved_value_now_valid"] == row["resolved"], (
            "a resolved row still holds a future dividend_last_paid"
        )


def test_registry_is_idempotent_by_construction():
    """Re-running the seed must not duplicate rows."""
    migration = (ROOT / "sql" / "migrations" / "V0038_quarantined_values.sql").read_text()
    seed = migration[migration.index("INSERT INTO audit.quarantined_values") :]
    assert "ON CONFLICT" in seed and "DO NOTHING" in seed
    # And the uniqueness it relies on must exist in the table definition.
    assert "UNIQUE (table_schema, table_name, column_name, row_key, observed_value)" in (migration)


def test_carry_forward_default_is_unchanged_by_quarantine_work():
    """Guard against the two efforts being coupled by accident."""
    assert settings.feature_carry_forward_days == 7
