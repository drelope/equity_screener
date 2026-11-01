"""Ingest dei security titles from filing XBRL instances into raw.sec_instrument_titles.

SEC's companyfacts JSON never exposes dei:SecurityTitle / dei:Security12bTitle
(only an allowlist of dei concepts), so the cover-page class titles have to be
read from each filing's XBRL financial-report instance (``*_htm.xml``), where
``dei:TradingSymbol`` sits next to the dei security title for every registered
class. This script picks the most recent suitable XBRL filing per issuer
(submissions payload already stored in raw.sec_submissions), downloads the
financial-report instance, pairs ``TradingSymbol`` <-> title per context, and
upserts one row per (cik, ticker) for ``classify_instrument`` to consume as the
exact bound dei title of the instrument.
Exact CIK/ticker titles also refresh active preferred display names and fill
missing title-parsed terms in reference.securities and raw.ticker_profile;
existing terms and issuer-level facts are not overwritten.

Usage:
    python -m scripts.populate_sec_instrument_titles
    python -m scripts.populate_sec_instrument_titles --preferred-only
    python -m scripts.populate_sec_instrument_titles --tickers ACR-PD,AAPL
    python -m scripts.populate_sec_instrument_titles --cik 0001332551
    python -m scripts.populate_sec_instrument_titles --limit 20
    python -m scripts.populate_sec_instrument_titles --file aapl_htm.xml --cik 0000320193
"""

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts.populate_dividend_data import summarize_ticker_profile
from src.crispdm.db import engine
from src.crispdm.doc_clauses import depositary_ratio
from src.crispdm.sec_client import (
    classify_security_type,
    filing_instance_url,
    parse_dei_instrument_titles,
)
from src.crispdm.stage import stage_exit_code
from src.crispdm.ticker_profile_store import upsert_ticker_profile


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()

# Forms whose cover page enumerates the issuer's registered classes, in
# preference order (annual reports first: the fullest cover lists every class).
FORM_PRIORITY = {
    "10-K": 0,
    "10-K/A": 0,
    "20-F": 1,
    "20-F/A": 1,
    "40-F": 2,
    "40-F/A": 2,
    "10-Q": 3,
    "10-Q/A": 3,
    "10-QT": 3,
    "10-QT/A": 3,
    "S-1": 4,
    "S-1/A": 4,
    "F-1": 4,
    "F-1/A": 4,
    "S-3": 4,
    "S-3/A": 4,
    "S-4": 4,
    "S-4/A": 4,
    "424B": 5,
    "424B1": 5,
    "424B2": 5,
    "424B3": 5,
    "424B4": 5,
    "424B5": 5,
    "F-3": 5,
    "F-4": 5,
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


def load_cik_universe(conn, tickers=None, cik=None, limit=None, preferred_only=False):
    """Distinct issuer CIKs to ingest, in deterministic order.

    Defaults to the active reference-securities universe so a bare run never
    downloads filings for deactivated tickers.
    """
    clauses = ["s.active = TRUE"]
    if preferred_only:
        clauses.append("s.security_type = 'preferred stock'")
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [t.upper() for t in tickers]
    if cik:
        clauses.append("s.cik = :cik")
        params["cik"] = normalize_cik(cik)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = " LIMIT :limit" if limit else ""
    rows = (
        conn.execute(
            text(f"""
        SELECT DISTINCT s.cik
        FROM reference.securities s
        JOIN raw.sec_submissions sub ON sub.cik = s.cik
        {where}
        ORDER BY s.cik
        {limit_sql}
    """),
            {**params, **({"limit": limit} if limit else {})},
        )
        .mappings()
        .all()
    )
    return [row["cik"] for row in rows]


def _xbrl_candidates(submissions_payload):
    """Every accepted XBRL cover-page filing in a submissions payload (unsorted)."""
    if not isinstance(submissions_payload, dict):
        return []

    filings = (submissions_payload.get("filings") or {}).get("recent") or {}
    index = range(len(filings.get("accessionNumber") or []))
    candidates = []
    for i in index:
        accession = (filings.get("accessionNumber") or [None] * len(index))[i]
        form = str((filings.get("form") or ["X"] * len(index))[i]).upper()
        is_xbrl = bool((filings.get("isXBRL") or [False] * len(index))[i])
        if not is_xbrl or form not in ACCEPTED_FORMS or not accession:
            continue
        candidates.append(
            {
                "accession": accession,
                "form": form,
                "filing_date": (filings.get("filingDate") or [None] * len(index))[i],
                "primary_document": (filings.get("primaryDocument") or [None] * len(index))[i],
            }
        )
    return candidates


def pick_best_filing(submissions_payload):
    """Choose the most recent XBRL cover-page filing from a submissions payload."""
    candidates = _xbrl_candidates(submissions_payload)
    candidates.sort(key=lambda item: item["filing_date"] or "", reverse=True)
    candidates.sort(key=lambda item: FORM_PRIORITY.get(item["form"], 99))
    return candidates[0] if candidates else None


#: Periodic reports. Their covers list every registered class, so a series listed after the
#: last annual report appears on the next quarterly cover.
PERIODIC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-QT", "10-QT/A"}


def pick_newer_cover_filing(submissions_payload, after_date):
    """The most recent periodic filing dated after ``after_date``, or None.

    ``pick_best_filing`` ranks annual reports first so the fullest cover wins, which means
    a class registered after the 10-K is invisible until the next one. This finds the newer
    quarterly cover that does list it.
    """
    if not after_date:
        return None
    newer = [
        item
        for item in _xbrl_candidates(submissions_payload)
        if item["form"] in PERIODIC_FORMS
        and item["primary_document"]
        and (item["filing_date"] or "") > after_date
    ]
    newer.sort(key=lambda item: item["filing_date"], reverse=True)
    return newer[0] if newer else None


def canonical_title_symbol(symbol, title, known_symbols):
    """Bind a filed spelling only to a unique symbol of this same issuer."""
    symbol = str(symbol).strip().upper()
    known = {str(value).strip().upper() for value in known_symbols or []}
    if symbol in known:
        return symbol
    compact = re.sub(r"[-./\s]", "", symbol)
    matches = {value for value in known if re.sub(r"[-./\s]", "", value) == compact}
    for value in known:
        match = re.fullmatch(r"(.+)-P([A-Z0-9]+)", value)
        if match and (
            compact in (f"{match[1]}P{match[2]}", f"{match[1]}PR{match[2]}")
            or (
                classify_security_type(title) == "preferred stock"
                and symbol in (f"{match[1]}-{match[2]}", f"{match[1]}.{match[2]}")
            )
        ):
            matches.add(value)
    return next(iter(matches)) if len(matches) == 1 else symbol


def apply_preferred_titles(conn, ciks):
    """Apply exact CIK/symbol titles and fill missing name-parsed terms, offline."""
    rows = (
        conn.execute(
            text("""
            SELECT s.security_id, s.ticker, s.security_name, s.coupon_rate,
                   s.liquidation_preference, t.title, tp.provider,
                   tp.coupon_rate AS profile_coupon, tp.coupon_type AS profile_coupon_type,
                   tp.liquidation_preference AS profile_preference
            FROM reference.securities s
            JOIN raw.sec_instrument_titles t ON t.cik = s.cik AND t.ticker = s.ticker
            LEFT JOIN raw.ticker_profile tp ON tp.security_id = s.security_id
            WHERE s.active AND s.security_type = 'preferred stock' AND s.cik = ANY(:ciks)
        """),
            {"ciks": ciks},
        )
        .mappings()
        .all()
    )
    updated = 0
    for row in rows:
        if classify_security_type(row["title"]) != "preferred stock":
            continue
        parsed = summarize_ticker_profile(row["ticker"], row["title"], "preferred stock")
        preference = parsed["liquidation_preference"]
        # The title may quote the underlying share, not the listed receipt.
        # Only the narrative miner establishes its per-depositary equivalent.
        if depositary_ratio(row["title"]) or preference is None or not 1 <= preference <= 1000:
            preference = None
        coupon = parsed["coupon_rate"]
        if parsed["coupon_type"] == "floating":
            coupon = None
        if (
            row["security_name"] != row["title"]
            or (row["coupon_rate"] is None and coupon is not None)
            or (row["liquidation_preference"] is None and preference is not None)
        ):
            conn.execute(
                text("""
                    UPDATE reference.securities
                    SET security_name = :title, coupon_rate = COALESCE(coupon_rate, :coupon),
                        liquidation_preference = COALESCE(liquidation_preference, :preference),
                        updated_at = now()
                    WHERE security_id = :security_id
                """),
                {**row, "coupon": coupon, "preference": preference},
            )
            updated += 1
        values = {}
        if row["profile_coupon"] is None and coupon is not None:
            values["coupon_rate"] = coupon
            if row["profile_coupon_type"] is None:
                values["coupon_type"] = parsed["coupon_type"]
        if row["profile_preference"] is None and preference is not None:
            values["liquidation_preference"] = preference
        if values:
            upsert_ticker_profile(
                conn,
                {
                    "security_id": row["security_id"],
                    "ticker": row["ticker"],
                    "provider": row["provider"] or "SEC_XBRL",
                    "raw_payload": {},
                    **values,
                },
                loader="populate_sec_instrument_titles",
                owned_columns=tuple(values),
                refreshed=False,
            )
    return updated


def ingest_from_instance(
    conn,
    cik,
    instance_xml,
    source_filing,
    source_url,
    document_hash,
    known_symbols,
    only_tickers=None,
):
    """Parse an instance and upsert its (symbol -> title) pairs.

    ``only_tickers`` restricts the write to those symbols, so a supplementary cover can
    fill a gap without replacing a title another filing already supplied. The return
    count then covers only the rows written.
    """
    pairs, titles = parse_dei_instrument_titles(instance_xml, known_symbols=known_symbols)
    touched = 0
    for ticker, title in pairs:
        ticker = canonical_title_symbol(ticker, title, known_symbols)
        if only_tickers is not None and ticker not in only_tickers:
            continue
        accession = (source_filing or {}).get("accession") or None
        filing_date = (source_filing or {}).get("filing_date") or None
        form_type = (source_filing or {}).get("form") or None
        conn.execute(
            text("""
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
        """),
            {
                "cik": cik,
                "ticker": ticker,
                "title": title,
                "accession": accession,
                "filing_date": filing_date,
                "form": form_type,
                "source_url": source_url,
                "document_hash": document_hash,
                "content_hash": title_row_hash(cik, ticker, title, accession, document_hash),
            },
        )
        touched += 1
    return (len(pairs) if only_tickers is None else touched), titles


def missing_preferred_tickers(conn, cik):
    """Active preferred tickers of ``cik`` that have no stored cover title at all."""
    return set(
        conn.execute(
            text("""
                SELECT s.ticker FROM reference.securities s
                WHERE s.cik = :cik AND s.active AND s.security_type = 'preferred stock'
                  AND NOT EXISTS (
                      SELECT 1 FROM raw.sec_instrument_titles t
                      WHERE t.cik = s.cik AND t.ticker = s.ticker
                  )
            """),
            {"cik": cik},
        ).scalars()
    )


def supplement_from_newer_filing(conn, cik, submission, best_filing, known_symbols, fetch=None):
    """Fill preferreds still without a title from a newer periodic cover.

    Costs one extra request, and only for an issuer that still has an active preferred
    with no title after the best filing was read. Returns the number of titles written.
    """
    missing = missing_preferred_tickers(conn, cik)
    if not missing:
        return 0
    newer = pick_newer_cover_filing(submission, (best_filing or {}).get("filing_date"))
    if not newer:
        return 0
    if REQUEST_DELAY:
        time.sleep(REQUEST_DELAY)
    url, instance_xml, document_hash = (fetch or filing_instance_url)(
        cik, newer["accession"], newer["primary_document"]
    )
    if not instance_xml:
        return 0
    with conn.begin_nested():
        rows, _titles = ingest_from_instance(
            conn,
            cik,
            instance_xml,
            {k: newer[k] for k in ("accession", "form", "filing_date")},
            url,
            document_hash,
            known_symbols,
            only_tickers=missing,
        )
    return rows


def populate_sec_instrument_titles(
    tickers=None, cik=None, limit=None, local_file=None, force=False, preferred_only=False
):
    """Run the ingest: fetch + parse instances and upsert paired titles."""
    if OFFLINE_ON and not local_file:
        with engine.connect() as conn:
            present = conn.execute(text("SELECT count(*) FROM raw.sec_instrument_titles")).scalar()
        print(
            "OFFLINE: no SEC fetch; stored titles remain "
            f"(raw.sec_instrument_titles rows: {present})."
        )
        return 0, 0, 0, 0

    processed = 0
    paired = 0
    skipped = 0
    errors = 0
    resume_skipped = 0
    supplemented_titles = 0
    with engine.begin() as conn:
        ciks = load_cik_universe(
            conn, tickers=tickers, cik=cik, limit=limit, preferred_only=preferred_only
        )
        for issuer_cik in ciks:
            try:
                if local_file:
                    if normalize_cik(cik) != issuer_cik:
                        continue
                    with open(local_file, "r", encoding="utf-8") as handle:
                        instance_xml = handle.read()
                    source_filing = {"accession": None, "form": local_file, "filing_date": None}
                    source_url = local_file
                    document_hash = hashlib.sha256(instance_xml.encode("utf-8")).hexdigest()
                    known_symbols = get_submission_symbols(conn, issuer_cik)
                else:
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
                    if not force and titles_stored_for_cik(conn, issuer_cik, filing["accession"]):
                        resume_skipped += 1
                        continue
                    url, instance_xml, document_hash = filing_instance_url(
                        issuer_cik, filing["accession"], filing["primary_document"]
                    )
                    if not instance_xml:
                        print(
                            f"  No XBRL instance for CIK {issuer_cik} "
                            f"({filing['form']} {filing['accession']})"
                        )
                        skipped += 1
                        continue
                    source_filing = {
                        "accession": filing["accession"],
                        "form": filing["form"],
                        "filing_date": filing["filing_date"],
                    }
                    source_url = url
                    known_symbols = get_submission_symbols(conn, issuer_cik)

                with conn.begin_nested():
                    rows, _titles = ingest_from_instance(
                        conn,
                        issuer_cik,
                        instance_xml,
                        source_filing,
                        source_url,
                        document_hash,
                        known_symbols,
                    )
                if not local_file:
                    supplemented = supplement_from_newer_filing(
                        conn, issuer_cik, submission, filing, known_symbols
                    )
                    rows += supplemented
                    supplemented_titles += supplemented
                paired += rows
                processed += 1
                if rows == 0:
                    skipped += 1
                if processed % 50 == 0:
                    print(f"  Processed {processed} issuers ({paired} paired titles)...")
            except Exception as exc:
                errors += 1
                print(f"  Error for CIK {issuer_cik}: {exc}")
        applied = apply_preferred_titles(conn, ciks)

    print(f"  Preferred reference titles/terms updated: {applied}")
    print(
        f"Completed: issuers={processed}, paired_titles={paired}, "
        f"skipped={skipped}, errors={errors}, resume_skipped={resume_skipped}, "
        f"supplemented_from_newer_filing={supplemented_titles}"
    )
    return processed, paired, skipped, errors


def get_submission_payload(conn, cik):
    return conn.execute(
        text("SELECT raw_payload FROM raw.sec_submissions WHERE cik = :cik"), {"cik": cik}
    ).scalar()


def get_submission_symbols(conn, cik):
    symbols = list(
        conn.execute(
            text("SELECT DISTINCT ticker FROM reference.securities WHERE cik = :cik AND active"),
            {"cik": cik},
        ).scalars()
    )
    if symbols:
        return symbols
    payload = get_submission_payload(conn, cik) or {}
    return list(payload.get("tickers") or [])


def titles_stored_for_cik(conn, cik, accession):
    return conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM raw.sec_instrument_titles
                WHERE cik = :cik AND accession_no = :accession
            ) AND NOT EXISTS (
                SELECT 1 FROM reference.securities s
                WHERE s.cik = :cik AND s.active AND s.security_type = 'preferred stock'
                  AND NOT EXISTS (
                      SELECT 1 FROM raw.sec_instrument_titles t
                      WHERE t.cik = s.cik AND t.ticker = s.ticker
                        AND t.accession_no = :accession
                  )
            )
        """),
        {"cik": cik, "accession": accession},
    ).scalar()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument("--cik", help="Single issuer CIK (10-digit form optional)")
    parser.add_argument(
        "--preferred-only",
        action="store_true",
        help="Only issuers with active preferred securities",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to first N issuers (for testing)"
    )
    parser.add_argument(
        "--file",
        dest="local_file",
        help="Parse a local *_htm.xml file instead of fetching (requires --cik)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch issuers that already have stored titles "
        "(by default they are skipped for cheap resume)",
    )
    args = parser.parse_args()

    tickers = (
        [value.strip().upper() for value in args.tickers.split(",") if value.strip()]
        if args.tickers
        else None
    )
    if args.local_file and not args.cik:
        parser.error("--file requires --cik")

    try:
        processed, paired, skipped, errors = populate_sec_instrument_titles(
            tickers=tickers,
            cik=args.cik,
            limit=args.limit,
            local_file=args.local_file,
            force=args.force,
            preferred_only=args.preferred_only,
        )
        # An issuer whose filing carries no DEI title matching a known symbol is
        # a legitimate zero, counted as skipped rather than as a failure.
        code = stage_exit_code(
            "populate_sec_instrument_titles", processed, paired, skipped=skipped, errors=errors
        )
    except Exception as exc:
        print(f"dei title ingest failed: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
