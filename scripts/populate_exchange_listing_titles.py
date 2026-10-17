"""Fill issuer-named preferreds from the Nasdaq Trader symbol directory.

When an active preferred has no decisive SEC cover title (``raw.sec_instrument_titles``),
``reference.securities.security_name`` stays the issuer name. The name parser
then has no series, coupon or liquidation preference to read. The free, keyless
Nasdaq Trader directory (``nasdaqtraded.txt``) names every US-listed issue,
NYSE preferreds included, under the ``BASE$SERIES`` symbol form.

For each active preferred whose name is still the issuer name, and whose SEC
title (if any) is only a bare label such as ``5.40% Series L`` that names no
instrument type, the directory title:

* names a preferred: becomes ``security_name``, and fills a blank coupon or
  liquidation preference parsed from it (same guards as the SEC title stage;
  a rate missing from the directory title is taken from the bare SEC label);
* names notes/debentures, units, common stock or a warrant/right: the row is
  reclassified with ``classify_source = 'exchange_title'`` and the title kept
  as evidence. When the target type already has a row for the same CIK and
  ticker, the misclassified duplicate is deactivated instead;
* is anything else (``SCE TRUST VI``): left alone.

SEC cover titles that name the instrument type always win: stage 1a renames
preferreds and ``repair_security_classification`` reclassifies the rest.
``repair_ticker_profile_sec_terms`` (later in the nightly) re-parses the profile
columns from the new names.

The directory is snapshotted into ``raw.exchange_listings``. A failed download,
or ``SEC_ETL_OFFLINE=1``, falls back to the stored snapshot.

Usage:
    python -m scripts.populate_exchange_listing_titles --dry-run
    python -m scripts.populate_exchange_listing_titles
    python -m scripts.populate_exchange_listing_titles --tickers AGM-PI,F-PB
    python -m scripts.populate_exchange_listing_titles --file nasdaqtraded.txt
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path

import requests
from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.populate_dividend_data import parse_percent, summarize_ticker_profile
from src.crispdm.db import engine
from src.crispdm.doc_clauses import depositary_ratio
from src.crispdm.http_retry import request_with_backoff
from src.crispdm.sec_client import classify_security_type

DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
USER_AGENT = "dividend-equity-crispdm research (exchange symbol directory)"
#: A full directory lists ~13,000 symbols; a short body is a truncated download.
MIN_DIRECTORY_ROWS = 5000
RECLASSIFY_TYPES = ("common_stock", "corporate bond", "other_debt_and_equity", "derivative")
CLEAR_COUPON_TYPES = ("common_stock", "derivative", "other_debt_and_equity")


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def directory_symbol(ticker):
    """Our ``AGM-PI`` / ``TFIN-P`` form to the directory's ``AGM$I`` / ``TFIN$``."""
    ticker = (ticker or "").strip().upper()
    match = re.fullmatch(r"([A-Z.]+)-P([A-Z]*)", ticker)
    return f"{match[1]}${match[2]}" if match else ticker


def parse_directory(body):
    """Directory rows as dicts; the trailing ``File Creation Time`` line is dropped."""
    rows = []
    for record in csv.DictReader(io.StringIO(body), delimiter="|"):
        symbol = (record.get("Symbol") or "").strip()
        name = (record.get("Security Name") or "").strip()
        if not symbol or not name or symbol.startswith("File Creation Time"):
            continue
        rows.append(
            {
                "symbol": symbol,
                "security_name": name,
                "listing_exchange": (record.get("Listing Exchange") or "").strip() or None,
                "etf": (record.get("ETF") or "").strip() == "Y",
                "test_issue": (record.get("Test Issue") or "").strip() == "Y",
            }
        )
    return rows


def fetch_directory(session=None):
    """Download the directory; ``None`` on any network failure."""
    session = session or requests.Session()
    try:
        response = request_with_backoff(
            session, "GET", DIRECTORY_URL, headers={"User-Agent": USER_AGENT}, timeout=60
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Nasdaq symbol directory unavailable ({exc}); using the stored snapshot.")
        return None
    return response.text


def store_listings(conn, rows, source_url):
    """Replace the snapshot, but only with a complete directory."""
    if len(rows) < MIN_DIRECTORY_ROWS:
        print(f"  Directory has only {len(rows)} rows; keeping the stored snapshot.")
        return 0
    conn.execute(text("DELETE FROM raw.exchange_listings"))
    conn.execute(
        text("""
            INSERT INTO raw.exchange_listings
                (symbol, security_name, listing_exchange, etf, test_issue, source_url)
            VALUES (:symbol, :security_name, :listing_exchange, :etf, :test_issue, :source_url)
            ON CONFLICT (symbol) DO NOTHING
        """),
        [{**row, "source_url": source_url} for row in rows],
    )
    return len(rows)


CANDIDATES_SQL = """
SELECT s.security_id, s.cik, s.ticker, s.dividend, s.security_name,
       s.coupon_rate, s.liquidation_preference,
       l.symbol, l.security_name AS title, l.source_url,
       (SELECT array_agg(t.title) FROM raw.sec_instrument_titles t
        WHERE t.cik = s.cik AND t.ticker = s.ticker) AS sec_titles
FROM reference.securities s
JOIN reference.issuers i ON i.cik = s.cik
JOIN raw.exchange_listings l ON l.symbol = :symbol_expr
WHERE s.active
  AND s.security_type = 'preferred stock'
  AND (s.security_name IS NULL
       OR upper(btrim(s.security_name)) = upper(btrim(i.issuer_name)))
  AND NOT l.etf AND NOT l.test_issue
  {ticker_filter}
ORDER BY s.ticker
"""

#: SQL twin of :func:`directory_symbol`.
SYMBOL_SQL = (
    "CASE WHEN s.ticker ~ '^[A-Z.]+-P[A-Z]*$' "
    "THEN regexp_replace(s.ticker, '^([A-Z.]+)-P([A-Z]*)$', '\\1$\\2') ELSE s.ticker END"
)


def has_decisive_sec_title(row):
    """An SEC cover title that names the instrument type wins (stage 1a and the
    classification repair own it); a bare ``5.40% Series L`` label does not."""
    return any(classify_security_type(title) != "other" for title in row.get("sec_titles") or [])


def load_candidates(conn, tickers=None, limit=None):
    ticker_filter = "AND s.ticker = ANY(:tickers)" if tickers else ""
    sql = CANDIDATES_SQL.replace(":symbol_expr", SYMBOL_SQL).format(ticker_filter=ticker_filter)
    rows = conn.execute(text(sql), {"tickers": tickers or []}).mappings().all()
    rows = [row for row in rows if not has_decisive_sec_title(row)]
    return rows[:limit] if limit else rows


#: Corporate-form words that end the issuer part of an exchange title
#: ("Gabelli Equity Trust, Inc. (The) Pfd Ser H").
ISSUER_SUFFIX_RE = re.compile(
    r"\b(?:inc|incorporated|corporation|corp|company|co|limited|ltd|plc|llc|l\.p|fund|trust"
    r"|bancorp)\b\.?,?(?:\s*\(the\))?",
    re.IGNORECASE,
)
COMMON_RE = re.compile(r"\bcommon\s+(?:stock|shares?)\b", re.IGNORECASE)


def instrument_part(title):
    """The title after the issuer name, so a fund called "... Preferred and
    Income Fund" is not read as a preferred. Titles with no corporate suffix
    ("Public Storage 6.000% Cumulative Preferred Shares") are kept whole."""
    matches = list(ISSUER_SUFFIX_RE.finditer(title))
    return title[matches[-1].end() :].strip(" -,") if matches else title


def title_security_type(title):
    instrument = instrument_part(title)
    if not instrument:
        return None
    if COMMON_RE.search(instrument):
        return "common_stock"
    return classify_security_type(instrument)


def plan_action(row):
    """``('rename', coupon, preference)``, ``('reclassify', type)`` or ``None``."""
    title = row["title"]
    kind = title_security_type(title)
    if kind == "preferred stock":
        parsed = summarize_ticker_profile(row["ticker"], title, "preferred stock")
        preference = parsed["liquidation_preference"]
        if depositary_ratio(title) or preference is None or not 1 <= preference <= 1000:
            preference = None
        coupon = None if parsed["coupon_type"] == "floating" else parsed["coupon_rate"]
        if coupon is None and parsed["coupon_type"] != "floating":
            # The bare SEC label ("5.40% Series L") still states the rate when
            # the exchange title ("Pfd Ser L %") drops it.
            coupon = next(
                (rate for rate in map(parse_percent, row.get("sec_titles") or []) if rate), None
            )
        return ("rename", coupon, preference)
    if kind in RECLASSIFY_TYPES:
        return ("reclassify", kind)
    return None


def _evidence(row, new_type):
    return json.dumps(
        {
            "exchange_title": row["title"],
            "directory_symbol": row["symbol"],
            "source_url": row["source_url"],
            "classified_as": new_type,
        }
    )


def apply_titles(conn, rows):
    """Apply every planned action; return ``{action: [tickers]}``."""
    done = {"renamed": [], "reclassified": [], "deactivated": [], "skipped": []}
    for row in rows:
        action = plan_action(row)
        if action is None:
            done["skipped"].append(row["ticker"])
            continue
        if action[0] == "rename":
            _, coupon, preference = action
            conn.execute(
                text("""
                    UPDATE reference.securities
                    SET security_name = :title,
                        coupon_rate = COALESCE(coupon_rate, :coupon),
                        liquidation_preference = COALESCE(liquidation_preference, :preference),
                        updated_at = now()
                    WHERE security_id = :security_id
                """),
                {**row, "coupon": coupon, "preference": preference},
            )
            done["renamed"].append(row["ticker"])
            continue

        new_type = action[1]
        twin = conn.execute(
            text("""
                SELECT 1 FROM reference.securities
                WHERE cik = :cik AND ticker = :ticker AND security_type = :new_type
                  AND dividend = :dividend AND security_id <> :security_id
            """),
            {**row, "new_type": new_type},
        ).first()
        params = {**row, "new_type": new_type, "evidence": _evidence(row, new_type)}
        if twin:
            # The unique (cik, ticker, type, dividend) key forbids a second row of
            # the real type, so retire the misclassified duplicate instead.
            conn.execute(
                text("""
                    UPDATE reference.securities
                    SET active = FALSE, security_name = :title,
                        classification_evidence = CAST(:evidence AS jsonb),
                        updated_at = now()
                    WHERE security_id = :security_id
                """),
                params,
            )
            done["deactivated"].append(row["ticker"])
            continue
        conn.execute(
            text("""
                UPDATE reference.securities
                SET security_type = :new_type, security_name = :title,
                    classify_source = 'exchange_title', classify_confidence = 'medium',
                    classification_evidence = CAST(:evidence AS jsonb),
                    liquidation_preference = NULL,
                    coupon_rate = CASE WHEN :clear_coupon THEN NULL ELSE coupon_rate END,
                    updated_at = now()
                WHERE security_id = :security_id
            """),
            {**params, "clear_coupon": new_type in CLEAR_COUPON_TYPES},
        )
        done["reclassified"].append(f"{row['ticker']}->{new_type}")
    return done


def populate_exchange_listing_titles(
    tickers=None, limit=None, local_file=None, dry_run=False, fetch=fetch_directory
):
    if local_file:
        body, source_url = Path(local_file).read_text(encoding="utf-8"), local_file
    elif _offline_enabled():
        body, source_url = None, DIRECTORY_URL
        print("OFFLINE: no directory download; using the stored snapshot.")
    else:
        body, source_url = fetch(), DIRECTORY_URL

    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            stored = store_listings(conn, parse_directory(body), source_url) if body else 0
            done = apply_titles(conn, load_candidates(conn, tickers=tickers, limit=limit))
        except Exception:
            transaction.rollback()
            raise
        if dry_run:
            transaction.rollback()
        else:
            transaction.commit()
    return stored, done


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument("--limit", type=int, help="Process at most N candidates")
    parser.add_argument("--file", help="Use a local nasdaqtraded.txt instead of downloading")
    parser.add_argument("--dry-run", action="store_true", help="Report, write nothing")
    args = parser.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    stored, done = populate_exchange_listing_titles(
        tickers=tickers, limit=args.limit, local_file=args.file, dry_run=args.dry_run
    )
    label = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"[{label}] directory rows stored: {stored}")
    for key in ("renamed", "reclassified", "deactivated", "skipped"):
        print(f"  {key}: {len(done[key])} {' '.join(done[key])}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
