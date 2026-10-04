"""Block until the warehouse accepts a connection, or exit non-zero.

An ``ExecStartPre`` gate for ``dividend-etl.service``. ``After=docker.service``
only orders the two units; it does not make docker ready, and the warehouse here
is a *container* that docker has to start on its own. Without this gate a 03:00
run races container startup and dies on a connection error that looks like a
pipeline fault rather than a boot race.

Exits 0 once a real query succeeds, 1 after ``--timeout`` seconds.
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from src.crispdm.db import engine  # noqa: E402


def wait_for_db(timeout, interval):
    deadline = time.monotonic() + timeout
    attempt = 0
    last = None
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return attempt, None
        except OperationalError as exc:
            last = getattr(exc.orig, "diag", None)
            last = getattr(last, "message_primary", None) or str(exc.orig)
            time.sleep(interval)
    return attempt, last


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds to keep retrying before failing the unit (default 300)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between attempts (default 5)",
    )
    args = parser.parse_args(argv)

    started = time.monotonic()
    attempts, last = wait_for_db(args.timeout, args.interval)
    waited = time.monotonic() - started
    if last is None:
        print(f"Warehouse reachable after {attempts} attempt(s) in {waited:.1f}s.")
        return 0
    print(
        f"Warehouse still unreachable after {attempts} attempt(s) in {waited:.1f}s: {last}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
