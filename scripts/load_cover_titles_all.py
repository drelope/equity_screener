"""One-time (and resumable) cover-title load for every issuer, not only preferred issuers.

The nightly runs ``populate_sec_instrument_titles --preferred-only``, so an issuer with no
preferred securities never has its cover read, and a note or preferred listed under it is
typed from the issuer's common-stock dividend tag (Navient's 6% Senior Notes, Strategy's
STRK preferred). This loads the covers for the rest.

The stage's own entry point runs the whole issuer list in one outer transaction, so a stop
part-way loses everything and the transaction is held for hours. This drives it one issuer
per transaction instead: progress is durable, a restart resumes (issuers that already have
a title are skipped), and ``--deadline`` ends the run cleanly so it can be fitted around the
nightly. Dividend payers are read first.

    python -m scripts.load_cover_titles_all --deadline 23:30
    python -m scripts.load_cover_titles_all --limit 200 --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import io
import time
from datetime import datetime

from scripts.populate_sec_instrument_titles import populate_sec_instrument_titles
from src.crispdm.db import read_df

ORDER_SQL = """
SELECT s.cik, bool_or(s.dividend) AS payer
FROM reference.securities s
JOIN raw.sec_submissions sub ON sub.cik = s.cik
WHERE s.active
  AND NOT EXISTS (SELECT 1 FROM raw.sec_instrument_titles t WHERE t.cik = s.cik)
GROUP BY s.cik
ORDER BY payer DESC, s.cik
"""


def pending_ciks(limit=None):
    """Issuers with no stored cover title at all, dividend payers first."""
    frame = read_df(ORDER_SQL)
    ciks = list(frame["cik"])
    return ciks[:limit] if limit else ciks


def parse_deadline(value: str | None, now: datetime | None = None):
    """``HH:MM`` today (local time) as a datetime, or None."""
    if not value:
        return None
    now = now or datetime.now()
    hour, minute = (int(part) for part in value.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def run(
    ciks, deadline=None, report_every=100, load=populate_sec_instrument_titles, clock=datetime.now
):
    totals = {"issuers": 0, "titled": 0, "no_titles": 0, "errors": 0, "stopped_at_deadline": False}
    started = time.monotonic()
    for index, cik in enumerate(ciks, start=1):
        if deadline and clock() >= deadline:
            totals["stopped_at_deadline"] = True
            break
        try:
            with contextlib.redirect_stdout(io.StringIO()):  # the stage prints one line per call
                processed, paired, _skipped, errors = load(cik=cik)
        except Exception as exc:  # noqa: BLE001 - one issuer must not stop the rest
            totals["errors"] += 1
            print(f"  {cik}: {type(exc).__name__}: {exc}", flush=True)
            continue
        totals["issuers"] += 1
        totals["errors"] += errors
        totals["titled" if paired else "no_titles"] += 1
        if index % report_every == 0:
            rate = index / max(time.monotonic() - started, 1e-9)
            print(
                f"  {index}/{len(ciks)} issuers, {totals['titled']} with titles, "
                f"{totals['errors']} errors, {rate:.2f}/s",
                flush=True,
            )
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline", help="Stop cleanly at this local time, HH:MM.")
    parser.add_argument("--limit", type=int, help="Only the first N pending issuers.")
    parser.add_argument("--dry-run", action="store_true", help="Count the issuers and stop.")
    args = parser.parse_args()
    ciks = pending_ciks(args.limit)
    print(f"{len(ciks)} issuers have no stored cover title", flush=True)
    if args.dry_run:
        return 0
    totals = run(ciks, parse_deadline(args.deadline))
    print(f"done: {totals}", flush=True)
    return 1 if totals["errors"] > max(10, len(ciks) // 20) else 0


if __name__ == "__main__":
    raise SystemExit(main())
