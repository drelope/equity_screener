"""Load the reviewed historical security artifact into reference tables.

Reads ``artifacts/historical_securities/historical_universe.csv``, produced by
``scripts.build_historical_universe``, and inserts the recovered delisted common
stocks as ``historical = TRUE`` securities. They are never active: the nightly
ETL, the dashboard book and the current-universe benchmark ignore them. Only
the opt-in historical backfill stages read them.

Two guards matter. A ticker is skipped when the current SEC snapshot maps it to
a different CIK, because a reused symbol would make the provider return the new
company's prices under the old company's id. A (cik, ticker) already present in
``reference.securities`` is left untouched, so a re-run is idempotent and a live
row is never converted.

Usage:
    python -m scripts.load_historical_securities --dry-run
    python -m scripts.load_historical_securities --limit 20
    python -m scripts.load_historical_securities
"""

import argparse
import csv
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine

DEFAULT_CSV = Path("artifacts/historical_securities/historical_universe.csv")
DEFAULT_MANIFEST = Path("artifacts/historical_securities/load_manifest.csv")


def security_id_for(ticker, cik, security_type):
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dividend-equity:{ticker.upper()}:{str(cik).zfill(10)}:{security_type}",
    )


def read_candidates(path, limit=None):
    """Rows that represent a recovered common stock, deduplicated by (cik, ticker)."""
    seen = set()
    rows = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("source") != "sec_cover_page":
                continue
            if row.get("security_type") != "common_stock":
                continue
            ticker = (row.get("ticker") or "").strip().upper()
            cik = (row.get("cik") or "").strip().zfill(10)
            if not ticker or not cik.isdigit():
                continue
            key = (cik, ticker)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "security_name": (row.get("title") or row.get("company_name") or ticker)[:500],
                    "company_name": (row.get("company_name") or ticker)[:500],
                    "sic": (row.get("sic") or "").strip(),
                    "last_filing": row.get("last_filing") or "",
                }
            )
            if limit is not None and len(rows) >= limit:
                break
    return rows


def existing_identities(conn, candidates):
    """The (cik, ticker) pairs already in the warehouse, and the current ticker map."""
    ciks = sorted({row["cik"] for row in candidates})
    tickers = sorted({row["ticker"] for row in candidates})
    present = set()
    for cik, ticker in conn.execute(
        text(
            "SELECT cik, ticker FROM reference.securities "
            "WHERE cik = ANY(:ciks) AND ticker = ANY(:tickers)"
        ),
        {"ciks": ciks, "tickers": tickers},
    ):
        present.add((str(cik).zfill(10), str(ticker).upper()))
    current = {}
    for ticker, cik in conn.execute(
        text("SELECT ticker, cik FROM raw.company_ticker WHERE ticker = ANY(:tickers)"),
        {"tickers": tickers},
    ):
        current[str(ticker).upper()] = str(cik).zfill(10)
    return present, current


def upsert_issuer(conn, cik, name, sic):
    issuer_id = conn.execute(
        text("SELECT issuer_id FROM reference.issuers WHERE cik = :cik"),
        {"cik": cik},
    ).scalar()
    if issuer_id is None:
        issuer_id = conn.execute(
            text(
                "INSERT INTO reference.issuers (cik, issuer_name, sic) "
                "VALUES (:cik, :name, :sic) RETURNING issuer_id"
            ),
            {"cik": cik, "name": name, "sic": sic or None},
        ).scalar_one()
    return issuer_id


def insert_security(conn, row):
    security_id = security_id_for(row["ticker"], row["cik"], "common_stock")
    issuer_id = upsert_issuer(conn, row["cik"], row["company_name"], row["sic"])
    conn.execute(
        text(
            """
            INSERT INTO reference.securities (
                ticker, cik, security_id, issuer_id, security_name, security_type,
                dividend, active, historical, currency, sec_data_status
            ) VALUES (
                :ticker, :cik, :sid, :issuer_id, :name, 'common_stock',
                TRUE, FALSE, TRUE, 'USD', 'unavailable'
            )
            ON CONFLICT (cik, ticker, security_type) DO UPDATE SET
                historical = TRUE,
                active = FALSE,
                updated_at = now()
            """
        ),
        {
            "ticker": row["ticker"],
            "cik": row["cik"],
            "sid": str(security_id),
            "issuer_id": issuer_id,
            "name": row["security_name"],
        },
    )
    return security_id


def load(candidates, dry_run=False):
    loaded = []
    skipped = []
    with engine.begin() as conn:
        present, current = existing_identities(conn, candidates)
        for row in candidates:
            key = (row["cik"], row["ticker"])
            if key in present:
                skipped.append({**row, "reason": "already_present"})
                continue
            other_cik = current.get(row["ticker"])
            if other_cik is not None and other_cik != row["cik"]:
                skipped.append({**row, "reason": f"ticker_reused_by_{other_cik}"})
                continue
            if dry_run:
                loaded.append(
                    {
                        **row,
                        "security_id": str(
                            security_id_for(row["ticker"], row["cik"], "common_stock")
                        ),
                    }
                )
                continue
            security_id = insert_security(conn, row)
            loaded.append({**row, "security_id": str(security_id)})
    return loaded, skipped


def write_manifest(loaded, skipped, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "cik",
                "company_name",
                "security_name",
                "sic",
                "last_filing",
                "security_id",
                "reason",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in loaded:
            writer.writerow({**row, "reason": "loaded"})
        for row in skipped:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Missing artifact: {args.csv}", file=sys.stderr)
        return 1
    candidates = read_candidates(args.csv, limit=args.limit)
    if not candidates:
        print("No recovered common stocks in the artifact.", file=sys.stderr)
        return 1
    loaded, skipped = load(candidates, dry_run=args.dry_run)
    write_manifest(loaded, skipped, args.manifest)
    reasons = {}
    for row in skipped:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    print(f"Candidates: {len(candidates)}")
    print(f"{'Would load' if args.dry_run else 'Loaded'}: {len(loaded)}")
    print(f"Skipped: {len(skipped)} ({reasons})")
    print(f"Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
