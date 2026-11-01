"""Snapshot SEC XBRL Frames into raw.xbrl_frames.

One request returns a concept for every filer over one period, so the cross-section
costs about one call per (concept, period) rather than one per company. Frames are
large, so they bypass the in-process ETag cache and are upserted straight away.

    python -m scripts.load_xbrl_frames
    python -m scripts.load_xbrl_frames --years 3 --concepts Assets NetIncomeLoss
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.frames import FRAME_CONCEPTS, FRAMES_URL, default_periods, rows_from_frame
from src.crispdm.sec_client import HEADERS, SEC_SESSION

UPSERT = text(
    """
    INSERT INTO raw.xbrl_frames
      (taxonomy, concept, unit, period, cik, entity_name, value, period_end, accession)
    VALUES
      (:taxonomy, :concept, :unit, :period, :cik, :entity_name, :value, :period_end, :accession)
    ON CONFLICT (taxonomy, concept, unit, period, cik) DO UPDATE SET
      entity_name = EXCLUDED.entity_name, value = EXCLUDED.value,
      period_end = EXCLUDED.period_end, accession = EXCLUDED.accession,
      retrieved_at = now()
    """
)


def fetch_frame(taxonomy: str, concept: str, unit: str, period: str) -> dict | None:
    """The frame payload, or None when SEC has no frame for that period yet."""
    url = FRAMES_URL.format(taxonomy=taxonomy, concept=concept, unit=unit, period=period)
    response = SEC_SESSION.get(url, headers=HEADERS, timeout=(10, 120))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5, help="Completed calendar years to load.")
    parser.add_argument("--concepts", nargs="*", help="Concept names; default the curated set.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    specs = [c for c in FRAME_CONCEPTS if not args.concepts or c[1] in args.concepts]
    failed = 0
    for taxonomy, concept, unit, kind in specs:
        for period in default_periods(kind, years=args.years):
            try:
                payload = fetch_frame(taxonomy, concept, unit, period)
            except Exception as exc:  # noqa: BLE001 - one bad frame must not stop the rest
                failed += 1
                print(f"  {concept} {period}: {exc}", flush=True)
                continue
            rows = rows_from_frame(taxonomy, concept, unit, period, payload or {})
            print(f"{concept} {period}: {len(rows)} filers", flush=True)
            if rows and not args.dry_run:
                with engine.begin() as conn:
                    for start in range(0, len(rows), 5000):
                        conn.execute(UPSERT, rows[start : start + 5000])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
