"""Load ALFRED vintages for every FRED-backed macro series.

Requesting the full real-time range returns one row per (observation, vintage), so
revisions are kept instead of overwritten. Series FRED does not revise simply have
one vintage per observation. Re-running upserts by (series, observation, vintage).

    python -m scripts.load_macro_vintages
    python -m scripts.load_macro_vintages --start 2015-01-01 --series IG_OAS HY_OAS
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from sqlalchemy import text

from src.crispdm import openbb_client as oc
from src.crispdm.db import engine
from src.crispdm.macro_inputs import SPECS
from src.crispdm.macro_vintages import rows_from_alfred

URL = "https://api.stlouisfed.org/fred/series/observations"
PAGE = 100_000  # FRED's per-request row limit

UPSERT = text(
    """
    INSERT INTO raw.macro_series_vintages
      (series_id, observation_date, vintage_date, value, unit, source, provider)
    VALUES (:series_id, :observation_date, :vintage_date, :value, :unit, :source, :provider)
    ON CONFLICT (series_id, observation_date, vintage_date) DO UPDATE SET
      value = EXCLUDED.value, retrieved_at = now()
    """
)


def _key() -> str | None:
    key = getattr(oc.obb.user.credentials, "fred_api_key", None)
    return key.get_secret_value() if hasattr(key, "get_secret_value") else key


class TooManyVintages(Exception):
    """ALFRED refuses a request spanning more than 2,000 vintage dates."""


def fetch_pages(fred_id, key, start, realtime_start, realtime_end, opener=urlopen):
    """Yield each page of ALFRED observations for one series and real-time window."""
    offset = 0
    while True:
        query = {
            "series_id": fred_id,
            "api_key": key,
            "file_type": "json",
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
            "observation_start": start,
            "limit": PAGE,
            "offset": offset,
        }
        for attempt in range(4):
            try:
                with opener(f"{URL}?{urlencode(query)}", timeout=60) as response:
                    payload = json.load(response)
                break
            except HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code == 400 and "vintage dates" in body:
                    raise TooManyVintages(body) from None
                if exc.code != 429 or attempt == 3:
                    raise RuntimeError(f"ALFRED HTTP {exc.code} for {fred_id}") from None
                time.sleep(30)
        yield payload
        offset += PAGE
        if offset >= int(payload.get("count", 0)):
            return


def fetch_vintages(fred_id, key, start, realtime_start, realtime_end, opener=urlopen):
    """All payloads for the window, bisecting it while ALFRED says it spans too many vintages.

    A bisected window clips the first vintage of a value already known at its start
    to that start, so a value can be stamped later than it was first published. That
    is conservative (never earlier), and the earlier window still carries the earlier
    vintage, so an as-of read before the split point is unaffected.
    """
    try:
        return list(fetch_pages(fred_id, key, start, realtime_start, realtime_end, opener))
    except TooManyVintages:
        low, high = date.fromisoformat(realtime_start), date.fromisoformat(realtime_end)
        if (high - low).days < 2:
            raise RuntimeError(f"ALFRED window too dense to split for {fred_id}") from None
        mid = low + (high - low) / 2
        return fetch_vintages(
            fred_id, key, start, low.isoformat(), mid.isoformat(), opener
        ) + fetch_vintages(
            fred_id, key, start, (mid + timedelta(days=1)).isoformat(), high.isoformat(), opener
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2010-01-01", help="Earliest observation date.")
    parser.add_argument("--series", nargs="*", help="Internal series ids; default all FRED series.")
    parser.add_argument(
        "--skip-if-no-key",
        action="store_true",
        help="Exit 0 instead of 1 when the API key is not configured (nightly use).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    key = _key()
    if not key:
        print("no FRED API key configured; cannot fetch ALFRED vintages")
        return 0 if args.skip_if_no_key else 1
    specs = [s for s in SPECS if s.fred_id and (not args.series or s.series_id in args.series)]
    failed = 0
    for spec in specs:
        try:
            rows = []
            for page in fetch_vintages(
                spec.fred_id, key, args.start, args.start, date.today().isoformat()
            ):
                rows += rows_from_alfred(spec.series_id, spec.unit, page)
        except RuntimeError as exc:
            failed += 1
            print(f"  {spec.series_id}: {exc}", flush=True)
            continue
        revised = len(rows) - len({(r["observation_date"]) for r in rows})
        print(f"{spec.series_id} ({spec.fred_id}): {len(rows)} vintages, {revised} revisions")
        if rows and not args.dry_run:
            with engine.begin() as conn:
                for start in range(0, len(rows), 5000):
                    conn.execute(UPSERT, rows[start : start + 5000])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
