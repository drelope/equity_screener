"""
Apply versioned PostgreSQL migrations from sql/migrations/ in order.

The schema is owned by two mechanisms:
  - ``scripts/init_db.py`` applies ``sql/schema.sql`` plus inline
    compatibility migrations to bring any pre-versioning database up to the
    current baseline (fresh installs also land here via the compose
    ``/docker-entrypoint-initdb.d`` mount).
  - ``scripts/migrate.py`` owns everything after that baseline. Each new
    schema change is a numbered SQL file ``sql/migrations/V0002_name.sql``;
    migrate.py records applied versions in ``schema_migrations`` and applies
    only those that are missing, in filename order, one transaction per file.

Running migrate.py against an already-initialized database (baseline tables
present, no tracking row) adopts the current state as version V0001 and then
applies any pending V0002+ files.

Usage:
    python -m scripts.migrate              # plan + apply pending migrations
    python -m scripts.migrate --plan       # print pending migrations only
"""

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "migrations"
BASELINE_VERSION = 1
FILENAME_RE = re.compile(r"^V(\d+)_([a-z0-9_]+)\.sql$", re.IGNORECASE)


class MigrationConflict(Exception):
    """Raised when on-disk migrations contradict the applied ledger."""

    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def tracking_table_exists(conn):
    return (
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'schema_migrations' OR table_name = 'schema_migrations'"
            )
        ).scalar()
        is not None
    )


def ensure_tracking_table(conn):
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    )


def applied_versions(conn):
    try:
        rows = conn.execute(
            text("SELECT version, name FROM public.schema_migrations ORDER BY version")
        ).fetchall()
    except ProgrammingError:
        return {}
    return {row[0]: row[1] for row in rows}


def adopt_current_state_as_baseline(conn, applied):
    """Record V0001 for an already-initialized DB with no tracking row.

    The baseline is the state produced by the schema.sql + init_db.py
    migrations, so we record rather than re-apply the original DDL.
    """
    if BASELINE_VERSION in applied:
        return False
    baseline_marker = "baseline: sql/schema.sql + scripts/init_db.py migrations"
    try:
        conn.execute(
            text(
                "INSERT INTO public.schema_migrations (version, name) "
                "VALUES (:v, :name) ON CONFLICT (version) DO NOTHING"
            ),
            {"v": BASELINE_VERSION, "name": baseline_marker},
        )
    except ProgrammingError:
        return False
    print(f"  adopted current schema as baseline V{BASELINE_VERSION}")
    return True


def discover_migrations(directory=None):
    """(version, filename, sql_text) tuples sorted by version."""
    migrations = []
    directory = directory or MIGRATIONS_DIR
    if directory.exists():
        for path in sorted(directory.glob("V*.sql")):
            match = FILENAME_RE.match(path.name)
            if not match:
                print(f"  [warn] ignoring {path.name}: does not match V####_name.sql")
                continue
            migrations.append((int(match.group(1)), path.name, path.read_text()))
    migrations.sort(key=lambda item: item[0])
    return migrations


def _migration_slug(name):
    """Reduce a ledger name or filename to a comparable slug.

    The ledger has not used a single naming convention: early inline migrations
    recorded short names without the ``V####_`` prefix or ``.sql`` suffix
    (e.g. ``committed_undrawn_facility``), while file-driven ones recorded the
    full filename. Comparing slugs avoids reporting those legacy rows as drift
    while still catching a genuine rename or edit.
    """
    slug = name.lower()
    if slug.endswith(".sql"):
        slug = slug[:-4]
    return re.sub(r"^v\d+_", "", slug)


def detect_migration_conflicts(applied, directory=None):
    """Return human-readable conflicts between on-disk migrations and the ledger.

    ``schema_migrations`` is keyed only on the integer version, so two files can
    silently collide:

      - **Duplicate version on disk.** Only the first file's SQL is applied; the
        second is never recorded and is skipped on every later run, so its
        schema change is silently lost. This happened when concurrent work
        created two different ``V0029`` files.
      - **Recorded name that no longer matches the file.** The file was edited
        or renamed after it was applied, so the database no longer reflects the
        file's current contents, and no run will ever re-apply it.

    Both are refusals rather than warnings: a migration runner that guesses at
    an ambiguous history is how a half-applied schema ships.
    """
    problems = []
    by_version = {}
    for version, name, _sql in discover_migrations(directory):
        by_version.setdefault(version, []).append(name)
    for version, names in sorted(by_version.items()):
        if len(names) > 1:
            problems.append(
                f"V{version:04d} is claimed by multiple files: {', '.join(sorted(names))}"
            )
        recorded = applied.get(version)
        if recorded is None:
            continue
        recorded_slug = _migration_slug(recorded)
        if not any(recorded_slug == _migration_slug(name) for name in names):
            problems.append(
                f"V{version:04d} is recorded as {recorded!r} but the file on disk "
                f"is {names[0]!r}: the migration was edited or renamed after apply"
            )
    return problems


def apply_migration(conn, version, name, sql_text):
    conn.execute(text(sql_text))
    conn.execute(
        text(
            "INSERT INTO public.schema_migrations (version, name) VALUES (:v, :name) "
            "ON CONFLICT (version) DO NOTHING"
        ),
        {"v": version, "name": name},
    )


def assert_no_migration_conflicts(applied, directory=None):
    problems = detect_migration_conflicts(applied, directory)
    if problems:
        raise MigrationConflict(problems)


def pending_migrations():
    """Migrations present on disk but not recorded as applied, as (version, name, sql)."""
    with engine.begin() as conn:
        ensure_tracking_table(conn)
        applied = applied_versions(conn)
        assert_no_migration_conflicts(applied)
        adopted = adopt_current_state_as_baseline(conn, applied)
        if adopted:
            applied[BASELINE_VERSION] = "baseline"
        return [m for m in discover_migrations() if m[0] not in applied]


def migrate(plan_only=False):
    with engine.begin() as conn:
        ensure_tracking_table(conn)
        applied = applied_versions(conn)
        assert_no_migration_conflicts(applied)
        adopted = adopt_current_state_as_baseline(conn, applied)
        if adopted:
            applied[BASELINE_VERSION] = "baseline"

        pending = [m for m in discover_migrations() if m[0] not in applied]
        print(f"schema_migrations: {len(applied)} applied, {len(pending)} pending")

        if plan_only:
            for version, name, _sql in pending:
                print(f"  pending: V{version:04d} {name}")
            return 0

        for version, name, sql_text in pending:
            print(f"  applying V{version:04d} {name} ...")
            apply_migration(conn, version, name, sql_text)
            print(f"  applied V{version:04d} {name}")
        print("migrations complete.")
    return 0


def check():
    """Report pending migrations and fail if any exist. Applies nothing.

    Deliberately a check rather than an auto-apply. A nightly that silently
    migrated its own schema would turn a deployment mistake into a data change
    nobody reviewed, and a migration that fails halfway would leave the run
    against a half-migrated database. Refusing to start is the recoverable
    outcome.
    """
    try:
        pending = pending_migrations()
    except MigrationConflict as exc:
        for problem in exc.problems:
            print(f"✗ {problem}", file=sys.stderr)
        print(
            "  Refusing to start: resolve the migration version conflict first.",
            file=sys.stderr,
        )
        return 1
    if not pending:
        print("✓ schema is up to date; no pending migrations")
        return 0
    print(
        f"✗ {len(pending)} pending migration(s) not applied: "
        + ", ".join(f"V{version:04d} {name}" for version, name, _sql in pending),
        file=sys.stderr,
    )
    print("  Apply them with: python -m scripts.migrate", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", action="store_true", help="Only list pending migrations, do not apply"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any migration is pending, without applying anything. "
        "Intended as a pipeline preflight: a stage that reads a column the database "
        "does not have yet fails at execution, and by then the run has already "
        "burned hours.",
    )
    args = parser.parse_args()
    try:
        if args.check:
            return check()
        return migrate(plan_only=args.plan)
    except MigrationConflict as exc:
        for problem in exc.problems:
            print(f"✗ {problem}", file=sys.stderr)
        print(
            "  Refusing to migrate: resolve the migration version conflict first.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"✗ migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
