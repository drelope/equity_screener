"""Load corporate actions from the FMP split CSV into raw.corporate_actions.

``scripts.fetch_fmp_splits`` writes ``artifacts/corporate_actions/fmp_splits.csv``;
this loads it into the warehouse so the price cleaner reads a table, not a file.
Each row carries a ``source_hash``, so reloading the same file inserts nothing.

    python -m scripts.load_corporate_actions
    python -m scripts.load_corporate_actions --path other.csv --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.crispdm.db import engine, read_df

DEFAULT_PATH = (
    Path(__file__).resolve().parents[1] / "artifacts" / "corporate_actions" / "fmp_splits.csv"
)
SOURCE = "FMP_SPLITS"

INSERT = text(
    """
    INSERT INTO raw.corporate_actions
      (security_id, ticker, action_type, effective_date, numerator, denominator,
       ratio, source, source_hash)
    VALUES
      (CAST(:security_id AS uuid), :ticker, 'split', :effective_date, :numerator,
       :denominator, :ratio, :source, :source_hash)
    ON CONFLICT (source_hash) DO NOTHING
    """
)


def source_hash(*parts) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def split_rows(raw: pd.DataFrame, securities: pd.DataFrame) -> list[dict]:
    """Valid splits as insert parameters. A ticker with no active match keeps a NULL security_id."""
    raw = raw.copy()
    raw["numerator"] = pd.to_numeric(raw["numerator"], errors="coerce")
    raw["denominator"] = pd.to_numeric(raw["denominator"], errors="coerce")
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["ticker", "date", "numerator", "denominator"])
    raw = raw[(raw["numerator"] > 0) & (raw["denominator"] > 0)]
    by_ticker: dict[str, list[str]] = {}
    for row in securities.itertuples():
        by_ticker.setdefault(str(row.ticker), []).append(str(row.security_id))
    rows = []
    for event in raw.itertuples():
        numerator, denominator = float(event.numerator), float(event.denominator)
        digest = source_hash(
            SOURCE, event.ticker, "split", event.date.date(), numerator, denominator
        )
        # A ticker shared by several identities yields one row per identity; the
        # hash includes the security so each is distinct.
        for security_id in by_ticker.get(str(event.ticker)) or [None]:
            rows.append(
                {
                    "security_id": security_id,
                    "ticker": str(event.ticker),
                    "effective_date": event.date.date(),
                    "numerator": numerator,
                    "denominator": denominator,
                    "ratio": denominator / numerator,
                    "source": SOURCE,
                    "source_hash": source_hash(digest, security_id),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.path.exists():
        print(f"no split file at {args.path}; run scripts.fetch_fmp_splits first")
        return 1
    raw = pd.read_csv(args.path, dtype={"ticker": str})
    securities = read_df(
        "SELECT security_id::text AS security_id, ticker FROM reference.securities "
        "WHERE security_type = 'common_stock'"
    )
    rows = split_rows(raw, securities)
    unresolved = sum(1 for r in rows if r["security_id"] is None)
    print(f"{len(rows)} split rows ({unresolved} with no matching security)")
    if args.dry_run or not rows:
        return 0
    with engine.begin() as conn:
        inserted = conn.execute(INSERT, rows).rowcount
    print(f"inserted {inserted}; {len(rows) - inserted} already loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
