"""Populate raw.macro_series and raw.macro_etf_sectors for the macro memo.

Economic inputs for the Inputs block of docs/GlobalMacroStrategy.md: the UST
curve, VIX, spot metals, ETF closes and sector weights from FMP, plus the
series FMP does not carry (SOFR, RRP, ICE BofA OAS, breakevens, TIPS real
yields, daily WTI/Brent/Henry Hub) from FRED. Every row records its source so
provenance stays auditable, and each series is fetched in one call for the
whole lookback window.

Supporting data only: nothing here feeds the model feature build.

Usage:
    python -m scripts.populate_macro_inputs
    python -m scripts.populate_macro_inputs --lookback-days 30
    python -m scripts.populate_macro_inputs --skip-fred
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.macro_inputs import LOOKBACK_DAYS_DEFAULT, collect_rows
from src.crispdm.stage import stage_exit_code


def upsert_series(conn, row):
    """Upsert one macro observation; returns 1."""
    conn.execute(
        text("""
        INSERT INTO raw.macro_series
            (series_id, observation_date, value, unit, source, provider, retrieved_at)
        VALUES (:series_id, :observation_date, :value, :unit, :source, :provider, now())
        ON CONFLICT (series_id, observation_date) DO UPDATE SET
            value = EXCLUDED.value,
            unit = EXCLUDED.unit,
            source = EXCLUDED.source,
            provider = EXCLUDED.provider,
            retrieved_at = now()
        """),
        {
            "series_id": row["series_id"],
            "observation_date": row["observation_date"],
            "value": row["value"],
            "unit": row["unit"],
            "source": row["source"],
            "provider": row["provider"],
        },
    )
    return 1


def upsert_sector(conn, row):
    """Upsert one ETF sector weight; returns 1."""
    conn.execute(
        text("""
        INSERT INTO raw.macro_etf_sectors
            (symbol, sector, weight, source, retrieved_at)
        VALUES (:symbol, :sector, :weight, :source, now())
        ON CONFLICT (symbol, sector) DO UPDATE SET
            weight = EXCLUDED.weight,
            source = EXCLUDED.source,
            retrieved_at = now()
        """),
        {
            "symbol": row["symbol"],
            "sector": row["sector"],
            "weight": row["value"],
            "source": row["source"],
        },
    )
    return 1


def populate_macro_inputs(
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
    include_fmp: bool = True,
    include_fred: bool = True,
):
    """Gather every registered macro series into raw.macro_series."""
    rows, sectors, stats = collect_rows(
        lookback_days=lookback_days,
        include_fmp=include_fmp,
        include_fred=include_fred,
        include_sectors=True,
    )
    written = 0
    if rows or sectors:
        with engine.begin() as conn:
            for row in rows:
                written += upsert_series(conn, row)
            for row in sectors:
                written += upsert_sector(conn, row)
    stats["written"] = written
    print(
        f"  macro rows: attempted={stats['attempted']} written={written} "
        f"empty={stats['empty']} errors={stats['errors']} skipped={stats['skipped']}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=LOOKBACK_DAYS_DEFAULT,
        help=f"Observation window per series (default {LOOKBACK_DAYS_DEFAULT})",
    )
    parser.add_argument("--skip-fmp", action="store_true", help="Do not gather FMP series")
    parser.add_argument("--skip-fred", action="store_true", help="Do not gather FRED series")
    args = parser.parse_args()
    try:
        stats = populate_macro_inputs(
            lookback_days=args.lookback_days,
            include_fmp=not args.skip_fmp,
            include_fred=not args.skip_fred,
        )
    except Exception as exc:
        print(f"✗ Error populating macro inputs: {exc}", file=sys.stderr)
        return 1
    print(
        f"\nMacro inputs: rows written={stats['written']}, empty={stats['empty']}, "
        f"errors={stats['errors']}, skipped={stats['skipped']}"
    )
    return stage_exit_code(
        "populate_macro_inputs",
        stats["attempted"],
        stats["written"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )


if __name__ == "__main__":
    sys.exit(main())
