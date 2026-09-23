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


def tracking_table_exists(conn):
    return conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'schema_migrations' OR table_name = 'schema_migrations'"
    )).scalar() is not None


def ensure_tracking_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))


def applied_versions(conn):
    try:
        rows = conn.execute(text(
            "SELECT version, name FROM public.schema_migrations ORDER BY version"
        )).fetchall()
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
        conn.execute(text(
            "INSERT INTO public.schema_migrations (version, name) "
            "VALUES (:v, :name) ON CONFLICT (version) DO NOTHING"
        ), {"v": BASELINE_VERSION, "name": baseline_marker})
    except ProgrammingError:
        return False
    print(f"  adopted current schema as baseline V{BASELINE_VERSION}")
    return True


def discover_migrations():
    """(version, filename, sql_text) tuples sorted by version."""
    migrations = []
    if MIGRATIONS_DIR.exists():
        for path in sorted(MIGRATIONS_DIR.glob("V*.sql")):
            match = FILENAME_RE.match(path.name)
            if not match:
                print(f"  [warn] ignoring {path.name}: does not match V####_name.sql")
                continue
            migrations.append((int(match.group(1)), path.name, path.read_text()))
    migrations.sort(key=lambda item: item[0])
    return migrations


def apply_migration(conn, version, name, sql_text):
    conn.execute(text(sql_text))
    conn.execute(text(
        "INSERT INTO public.schema_migrations (version, name) VALUES (:v, :name) "
        "ON CONFLICT (version) DO NOTHING"
    ), {"v": version, "name": name})


def migrate(plan_only=False):
    with engine.begin() as conn:
        ensure_tracking_table(conn)
        applied = applied_versions(conn)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true",
                        help="Only list pending migrations, do not apply")
    args = parser.parse_args()
    try:
        return migrate(plan_only=args.plan)
    except Exception as exc:
        print(f"✗ migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())