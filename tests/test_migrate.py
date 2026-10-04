from scripts import migrate as mig


def _write(directory, name, sql="SELECT 1;"):
    (directory / name).write_text(sql)


def test_discover_migrations_sorts_by_version_and_ignores_bad_names(tmp_path):
    _write(tmp_path, "V0005_second.sql")
    _write(tmp_path, "V0002_first.sql")
    _write(tmp_path, "not_a_migration.sql")

    versions = [v for v, _name, _sql in mig.discover_migrations(tmp_path)]

    assert versions == [2, 5]


def test_duplicate_version_on_disk_is_a_conflict(tmp_path):
    """Two files reusing a version silently lose the second one's schema change.

    migrate.py keys the ledger on the integer version, so a duplicate is applied
    at most once and then never again. This is the failure that produced the
    V0029 collision between concurrent work.
    """
    _write(tmp_path, "V0029_dividend_recency.sql")
    _write(tmp_path, "V0029_other_change.sql")

    problems = mig.detect_migration_conflicts({}, tmp_path)

    assert len(problems) == 1
    assert "V0029" in problems[0]
    assert "multiple files" in problems[0]


def test_recorded_name_drift_is_a_conflict(tmp_path):
    """A file renamed or edited after apply is never re-applied; surface it."""
    _write(tmp_path, "V0029_dividend_recency.sql")
    applied = {29: "V0029_something_else.sql"}

    problems = mig.detect_migration_conflicts(applied, tmp_path)

    assert len(problems) == 1
    assert "edited or renamed after apply" in problems[0]


def test_matching_ledger_is_not_a_conflict(tmp_path):
    _write(tmp_path, "V0029_dividend_recency.sql")
    _write(tmp_path, "V0030_other.sql")
    applied = {29: "V0029_dividend_recency.sql", 30: "V0030_other.sql"}

    assert mig.detect_migration_conflicts(applied, tmp_path) == []


def test_baseline_marker_without_a_file_is_not_a_conflict(tmp_path):
    """The adopted V0001 baseline is recorded without an on-disk V0001 file."""
    _write(tmp_path, "V0029_dividend_recency.sql")
    applied = {1: "baseline: sql/schema.sql + scripts/init_db.py migrations"}

    assert mig.detect_migration_conflicts(applied, tmp_path) == []


def test_legacy_short_ledger_name_is_not_a_conflict(tmp_path):
    """Early inline migrations recorded short names like ``c4_audit_warning``.

    The ledger mixes conventions: V0019-V0022 have no ``V####_`` prefix or
    ``.sql`` suffix. Those must not be reported as drift, or every plan/check
    call would refuse to run.
    """
    _write(tmp_path, "V0019_c4_audit_warning.sql")
    _write(tmp_path, "V0022_committed_undrawn_facility.sql")
    applied = {19: "c4_audit_warning", 22: "committed_undrawn_facility"}

    assert mig.detect_migration_conflicts(applied, tmp_path) == []


def test_assert_no_migration_conflicts_raises_with_problems(tmp_path):
    _write(tmp_path, "V0007_a.sql")
    _write(tmp_path, "V0007_b.sql")

    try:
        mig.assert_no_migration_conflicts({}, tmp_path)
    except mig.MigrationConflict as exc:
        assert exc.problems and "V0007" in exc.problems[0]
    else:
        raise AssertionError("expected MigrationConflict")
