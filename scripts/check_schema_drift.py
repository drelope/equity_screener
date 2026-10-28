"""Report schema drift between the live database and the repository.

`scripts/migrate.py --check` answers "are all migrations applied?". This answers the
other question: "is the database actually in the state the repository describes?"

The two are not the same. During an audit a view was replaced with an older
definition by hand; `--check` reported "schema is up to date; no pending
migrations", because the ledger was intact and the object was not. Nothing in the
migration path could notice, and re-running the migrator would not have repaired it.

So the reference is not a checked-in expectation file -- those drift too, and this
repository already has one behind by 51 objects. The reference is built: a scratch
database is created, `sql/schema.sql` and `scripts/init_db.py`'s inline migrations
are applied, then every versioned migration in order. If that build does not match
the live catalog, the repository and the database disagree, and the report says
which objects and how.

Read-only with respect to the live database. The scratch database is created and
dropped; nothing else is touched, and no data is read.

Usage:
    python -m scripts.check_schema_drift            # human-readable report
    python -m scripts.check_schema_drift --quiet    # only report the verdict

Exit status is 0 when the two agree and 1 when they do not, so it can gate a
deploy the way `migrate --check` does.
"""

from __future__ import annotations

import argparse
import ast
import signal
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scripts.migrate import apply_migration, discover_migrations, ensure_tracking_table
from src.crispdm.config import settings
from src.crispdm.schema_fingerprint import diff, fingerprint, format_report, oneline

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Differences between the live database and the repository that are known,
# understood, and deliberately left in place. Anything listed here is still
# printed, so the count of accepted drift is visible; it just does not fail the
# check. Adding an entry means accepting the difference permanently, so each one
# carries the reason and what it would cost to close.
# Empty: the one long-standing entry, reference.securities_security_id_key, was
# closed by V0077, which re-pointed every FK at the primary key and dropped the
# redundant UNIQUE. Kept as the hook for the next understood-but-unfixed one.
ACCEPTED_DIFFERENCES = {}


def partition(problems, accepted=ACCEPTED_DIFFERENCES):
    """Split into (unexplained, accepted) using the object name, not the full key.

    A constraint and the index backing it share a name, so one entry covers both
    keys the checker emits for a single object.
    """
    unexplained, acknowledged = [], []
    for problem in problems:
        _, key, *_ = problem
        name = key.split(" ", 1)[-1] if " " in key else key
        (acknowledged if name in accepted else unexplained).append(problem)
    return unexplained, acknowledged


def init_db_inline_migrations(path: Path | None = None) -> list[str]:
    """Read `init_db.py`'s inline migration list without importing the module.

    `init_db.py` applies its migrations at module scope, so importing it to reuse
    the list would create and initialise a database as a side effect. Parsing the
    assignment out of the source keeps this check incapable of that.
    """
    path = path or PROJECT_ROOT / "scripts" / "init_db.py"
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "migrations" for target in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise RuntimeError(f"no `migrations` list found in {path}")


def scratch_url(live_url: str, database: str) -> str:
    """Same server, different database.

    Parsed rather than pattern-matched: a regular expression cannot tell a
    database name from the rest of a DSN, and one that guessed would build the
    reference against a server URL instead of a database.
    """
    url = make_url(live_url)
    if not url.database:
        raise RuntimeError(f"{live_url!r} names no database to build a reference beside")
    return url.set(database=database).render_as_string(hide_password=False)


def build_reference(database: str, *, progress=None):
    """Create `database`, apply schema.sql, init_db's inline migrations, then V0001+.

    Returns the SQLAlchemy engine for it. Mirrors `scripts/init_db.py` followed by
    `scripts/migrate.py`, which is the order the two scripts are documented to run.
    """
    live_url = settings.database_url
    admin = create_engine(live_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        conn.execute(text(f'CREATE DATABASE "{database}"'))

    engine = create_engine(scratch_url(live_url, database))
    schema = (PROJECT_ROOT / "sql" / "schema.sql").read_text()
    inline = init_db_inline_migrations()

    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(schema)
        if progress:
            progress("  schema.sql applied")
        for statement in inline:
            with raw.cursor() as cur:
                cur.execute(statement)
        if progress:
            progress(f"  {len(inline)} init_db inline statements applied")

    with engine.begin() as conn:
        ensure_tracking_table(conn)
    for version, name, sql_text in discover_migrations():
        with engine.begin() as conn:
            apply_migration(conn, version, name, sql_text)
        if progress:
            progress(f"  V{version:04d} {name}")
    return engine, admin


def drop_reference(database: str, engine=None, admin=None) -> None:
    """Terminate stragglers and drop the scratch database.

    Keyed on the database name rather than the engine, so a failure partway through
    the build still cleans up the database it already created.
    """
    if engine is not None:
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001, S110 - disposal must not block cleanup
            pass
    admin = admin or create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
    finally:
        admin.dispose()


def _raise_system_exit(signum, _frame):
    """Convert SIGTERM into a SystemExit so ``finally`` runs.

    Python's default SIGTERM disposition kills the process outright, without
    unwinding ``try/finally``. A build killed that way -- by ``timeout``, a
    stopping ops worker, ``docker stop`` or a closed session -- never reaches
    ``drop_reference`` and leaks its half-built scratch database (the two
    ``schema_ref_*`` databases found on 2026-10-13 were exactly that). Exiting
    through SystemExit takes the normal cleanup path.
    """
    raise SystemExit(128 + signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="Print only the verdict, not the object list"
    )
    parser.add_argument(
        "--keep-reference",
        action="store_true",
        help="Leave the scratch database in place for inspection",
    )
    args = parser.parse_args()

    database = f"schema_ref_{uuid.uuid4().hex[:12]}"
    progress = None if args.quiet else print

    signal.signal(signal.SIGTERM, _raise_system_exit)

    reference = None
    admin = None
    try:
        print(f"building reference database {database} from the repository ...")
        reference, admin = build_reference(database, progress=progress)

        with create_engine(settings.database_url).connect() as live_conn:
            live = fingerprint(live_conn)
        with reference.connect() as ref_conn:
            ref = fingerprint(ref_conn)
    except Exception as exc:  # noqa: BLE001 - report, do not crash the pipeline
        print(f"✗ could not build the reference schema: {exc}", file=sys.stderr)
        print(
            "  A build failure is itself drift: the repository cannot reproduce the "
            "database. Fix the bootstrap before trusting this check.",
            file=sys.stderr,
        )
        return 1
    finally:
        if args.keep_reference:
            print(f"reference database left in place: {database}")
        else:
            drop_reference(database, reference, admin)

    problems = diff(live, ref)
    print(f"\nlive: {len(live)} objects   reference: {len(ref)} objects")

    unexplained, acknowledged = partition(problems)
    if acknowledged:
        print(f"\n{len(acknowledged)} accepted difference(s):")
        for _, key, live_value, _reference_value in acknowledged:
            name = key.split(" ", 1)[-1]
            print(f"  accepted: {key}")
            print(f"      {oneline(ACCEPTED_DIFFERENCES[name], 300)}")

    if not unexplained:
        print("\n✓ live schema matches the repository")
        return 0

    print(f"\n{format_report(unexplained)}", file=sys.stderr)
    print(
        "\nThe database and the repository disagree. Either the database was changed "
        "outside the migration runner, or a migration and schema.sql need updating.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
