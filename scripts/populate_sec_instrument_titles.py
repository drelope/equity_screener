"""Ingest dei security titles from filing XBRL instances into raw.sec_instrument_titles.

SEC's companyfacts JSON never exposes dei:SecurityTitle / dei:Security12bTitle
(only an allowlist of dei concepts), so the cover-page class titles have to be
read from each filing's XBRL financial-report instance (``*_htm.xml``), where
``dei:TradingSymbol`` sits next to the dei security title for every registered
class. This script picks the most recent suitable XBRL filing per issuer
(submissions payload already stored in raw.sec_submissions), downloads the
financial-report instance, pairs ``TradingSymbol`` <-> title per period, and
upserts one row per (cik, ticker) for ``classify_instrument`` to consume as the
exact bound dei title of the instrument.

Usage:
    python -m scripts.populate_sec_instrument_titles
    python -m scripts.populate_sec_instrument_titles --tickers ACR-PD,AAPL
    python -m scripts.populate_sec_instrument_titles --cik 0001332551
    python -m scripts.populate_sec_instrument_titles --limit 20
    python -m scripts.populate_sec_instrument_titles --file aapl_htm.xml --cik 0000320193
"""
import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.sec_client import (
    filing_instance_url,
    parse_dei_instrument_titles,
)


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()

# Forms whose cover page enumerates the issuer's registered classes, in
# preference order (annual reports first: the fullest cover lists every class).
FORM_PRIORITY = {
    "10-K": 0, "10-K/A": 0,
    "20-F": 1, "20-F/A": 1,
    "40-F": 2, "40-F/A": 2,
    "10-Q": 3, "10-Q/A": 3,
    "10-QT": 3, "10-QT/A": 3,
    "S-1": 4, "S-1/A": 4,
    "F-1": 4, "F-1/A": 4,
    "S-3": 4, "S-3/A": 4,
    "S-4": 4, "S-4/A": 4,
    "424B": 5, "424B1": 5, "424B2": 5, "424B3": 5, "424B4": 5, "424B5": 5,
    "F-3": 5, "F-4": 5,
    "8-K": 6,
}

ACCEPTED_FORMS = set(FORM_PRIORITY)

# SEC asks for <=10 requests/second; a modest gap keeps bulk runs polite.
REQUEST_DELAY = float(os.environ.get("SEC_REQUEST_DELAY", ".25"))


def normalize_cik(cik):
    return str(int(str(cik).strip())).zfill(10)


def title_row_hash(cik, ticker, title, accession, document_hash):
    return hashlib.sha256(
        f"{cik}|{ticker}|{title}|{accession}|{document_hash}".encode("utf-8")
    ).hexdigest()


def load_cik_universe(conn, tickers=None, cik=None, limit=None):
    """Distinct issuer CIKs to ingest, in deterministic order."""
    clauses = []
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [t.upper() for t in tickers]
    if cik:
        clauses.append("s.cik = :cik")
        params["cik"] = normalize_cik(cik)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = " LIMIT :limit" if limit else ""
    rows = conn.execute(text(f"""
        SELECT DISTINCT s.cik
        FROM reference.securities s
        JOIN raw.sec_submissions sub ON sub.cik = s.cik
        {where}
        ORDER BY s.cik
        {limit_sql}
    """), {**params, **({"limit": limit} if limit else {})}).mappings().all()
    return [row["cik"] for row in rows]


def pick_best_filing(submissions_payload):
    """Choose the most recent XBRL cover-page filing from a submissions payload."""
    if not isinstance(submissions_payload, dict):
        return None

    filings = (submissions_payload.get("filings") or {}).get("recent") or {}
    index = range(len(filings.get("accessionNumber") or []))
    candidates = []
    for i in index:
        accession = (filings.get("accessionNumber") or [None] * len(index))[i]
        form = str((filings.get("form") or ["X"] * len(index))[i]).upper()
        is_xbrl = bool((filings.get("isXBRL") or [False] * len(index))[i])
        if not is_xbrl or form not in ACCEPTED_FORMS or not accession:
            continue
        candidates.append({
            "accession": accession,
            "form": form,
            "filing_date": (filings.get("filingDate") or [None] * len(index))[i],
            "primary_document": (filings.get("primaryDocument") or [None] * len(index))[i],
        })
    candidates.sort(key=lambda item: item["filing_date"] or "", reverse=True)
    candidates.sort(key=lambda item: FORM_PRIORITY.get(item["form"], 99))
    return candidates[0] if candidates else None


def ingest_from_instance(conn, cik, instance_xml, source_filing, source_url,
                         document_hash, known_symbols):
    """Parse an instance and upsert its (symbol -> title) pairs."""
    pairs, titles = parse_dei_instrument_titles(instance_xml, known_symbols=known_symbols)
    touched = 0
    for ticker, title in pairs:
        accession = (source_filing or {}).get("accession") or None
        filing_date = (source_filing or {}).get("filing_date") or None
        form_type = (source_filing or {}).get("form") or None
        previous = conn.execute(text(
            "SELECT title FROM raw.sec_instrument_titles "
            "WHERE cik = :cik AND ticker = :ticker"
        ), {"cik": cik, "ticker": ticker}).scalar()
        conn.execute(text("""
            INSERT INTO raw.sec_instrument_titles
                (cik, ticker, title, accession_no, filing_date, form_type,
                 source_url, document_hash, content_hash, retrieved_at)
            VALUES (:cik, :ticker, :title, :accession, :filing_date, :form,
                    :source_url, :document_hash, :content_hash, now())
            ON CONFLICT (cik, ticker) DO UPDATE SET
                title = EXCLUDED.title,
                accession_no = EXCLUDED.accession_no,
                filing_date = EXCLUDED.filing_date,
                form_type = EXCLUDED.form_type,
                source_url = EXCLUDED.source_url,
                document_hash = EXCLUDED.document_hash,
                content_hash = EXCLUDED.content_hash,
                retrieved_at = now()
        """), {
            "cik": cik,
            "ticker": ticker,
            "title": title,
            "accession": accession,
            "filing_date": filing_date,
            "form": form_type,
            "source_url": source_url,
            "document_hash": document_hash,
            "content_hash": title_row_hash(cik, ticker, title, accession, document_hash),
        })
        touched += 1
    return len(pairs), titles


def populate_sec_instrument_titles(tickers=None, cik=None, limit=None,
                                   local_file=None, force=False):
    """Run the ingest: fetch + parse instances and upsert paired titles."""
    if OFFLINE_ON and not local_file:
        with engine.connect() as conn:
            present = conn.execute(text(
                "SELECT count(*) FROM raw.sec_instrument_titles"
            )).scalar()
        print("OFFLINE: no SEC fetch; stored titles remain "
              f"(raw.sec_instrument_titles rows: {present}).")
        return 0

    processed = 0
    paired = 0
    skipped = 0
    errors = 0
    resume_skipped = 0
    with engine.begin() as conn:
        ciks = load_cik_universe(conn, tickers=tickers, cik=cik, limit=limit)
        for issuer_cik in ciks:
            try:
                if local_file:
                    if normalize_cik(cik) != issuer_cik:
                        continue
                    with open(local_file, "r", encoding="utf-8") as handle:
                        instance_xml = handle.read()
                    source_filing = {"accession": None, "form": local_file,
                                     "filing_date": None}
                    source_url = local_file
                    document_hash = hashlib.sha256(
                        instance_xml.encode("utf-8")).hexdigest()
                    known_symbols = get_submission_symbols(conn, issuer_cik)
                else:
                    if not force and titles_stored_for_cik(conn, issuer_cik):
                        resume_skipped += 1
                        continue
                    if REQUEST_DELAY:
                        time.sleep(REQUEST_DELAY)
                    submission = get_submission_payload(conn, issuer_cik)
                    if not submission:
                        skipped += 1
                        continue
                    filing = pick_best_filing(submission)
                    if not filing or not filing["primary_document"]:
                        skipped += 1
                        continue
                    url, instance_xml, document_hash = filing_instance_url(
                        issuer_cik, filing["accession"], filing["primary_document"]
                    )
                    if not instance_xml:
                        print(f"  No XBRL instance for CIK {issuer_cik} "
                              f"({filing['form']} {filing['accession']})")
                        skipped += 1
                        continue
                    source_filing = {"accession": filing["accession"],
                                     "form": filing["form"],
                                     "filing_date": filing["filing_date"]}
                    source_url = url
                    known_symbols = get_submission_symbols(conn, issuer_cik)

                rows, _titles = ingest_from_instance(
                    conn, issuer_cik, instance_xml, source_filing, source_url,
                    document_hash, known_symbols,
                )
                paired += rows
                processed += 1
                if rows == 0:
                    skipped += 1
                if processed % 50 == 0:
                    print(f"  Processed {processed} issuers ({paired} paired titles)...")
            except Exception as exc:
                errors += 1
                print(f"  Error for CIK {issuer_cik}: {exc}")

    print(f"Completed: issuers={processed}, paired_titles={paired}, "
          f"skipped={skipped}, errors={errors}, resume_skipped={resume_skipped}")
    return processed


def get_submission_payload(conn, cik):
    return conn.execute(text(
        "SELECT raw_payload FROM raw.sec_submissions WHERE cik = :cik"
    ), {"cik": cik}).scalar()


def get_submission_symbols(conn, cik):
    payload = get_submission_payload(conn, cik) or {}
    return list(payload.get("tickers") or [])


def titles_stored_for_cik(conn, cik):
    return conn.execute(text(
        "SELECT count(*) FROM raw.sec_instrument_titles WHERE cik = :cik"
    ), {"cik": cik}).scalar()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument("--cik", help="Single issuer CIK (10-digit form optional)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to first N issuers (for testing)")
    parser.add_argument("--file", dest="local_file",
                        help="Parse a local *_htm.xml file instead of fetching "
                             "(requires --cik)")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch issuers that already have stored titles "
                             "(by default they are skipped for cheap resume)")
    args = parser.parse_args()

    tickers = [value.strip().upper() for value in args.tickers.split(",")
               if value.strip()] if args.tickers else None
    if args.local_file and not args.cik:
        parser.error("--file requires --cik")

    try:
        populate_sec_instrument_titles(
            tickers=tickers, cik=args.cik, limit=args.limit,
            local_file=args.local_file, force=args.force,
        )
    except Exception as exc:
        print(f"dei title ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())