"""Build a historical issuer/ticker master from SEC EDGAR.

The warehouse's ``raw.company_ticker`` is the *current* SEC snapshot, so every
price series it carries belongs to a company still listed in 2026. Companies
that stopped trading during the backtest window are absent, which is the
survivorship bias the backtest carries. Their filings are still in EDGAR,
however, and the cover page of each filing's XBRL instance pairs
``dei:TradingSymbol`` with the registered class title. This script enumerates
issuers from the quarterly EDGAR full-index, diffs them against the warehouse,
and recovers a ticker for each missing issuer from its most recent filing.

The output is a reviewable CSV artifact; this script writes no warehouse rows.
It is resumable: the full-index files, submissions payloads and parsed tickers
are cached under ``artifacts/sec_historical``.

Usage:
    python -m scripts.build_historical_universe --resolve-limit 50
    python -m scripts.build_historical_universe
    python -m scripts.build_historical_universe --start-year 2018 --end-year 2026
    python -m scripts.build_historical_universe --refresh
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.sec_client import (
    classify_security_type,
    filing_instance_url,
    get_submissions,
    parse_dei_instrument_titles,
)

ARTIFACT_DIR = Path("artifacts/sec_historical")
INDEX_DIR = ARTIFACT_DIR / "company_index"
SUBMISSIONS_DIR = ARTIFACT_DIR / "submissions"
RESOLVED_DIR = ARTIFACT_DIR / "resolved"
OUTPUT = Path("artifacts/historical_securities/historical_universe.csv")

OPERATING_FORMS = {
    "10-K",
    "10-K/A",
    "10-KT",
    "10-KT/A",
    "10-Q",
    "10-Q/A",
    "10-QT",
    "10-QT/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
}

COVER_FORMS = {
    "10-K": 0,
    "10-K/A": 0,
    "10-KT": 0,
    "10-KT/A": 0,
    "20-F": 1,
    "20-F/A": 1,
    "40-F": 2,
    "40-F/A": 2,
    "10-Q": 3,
    "10-Q/A": 3,
    "10-QT": 3,
    "10-QT/A": 3,
}

INDEX_HEADER_OFFSET = 10


def index_url(year, quarter):
    return f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/company.idx"


def cached_text(path, fetch):
    if path.exists():
        return path.read_text(encoding="latin-1")
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="latin-1")
    return value


def parse_company_index(raw):
    """Parse a company.idx into rows of (name, form, cik, filed, file)."""
    rows = []
    lines = raw.splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith("Company Name")), None)
    start = (header + 2) if header is not None else INDEX_HEADER_OFFSET
    for line in lines[start:]:
        if not line.strip() or line.startswith("-"):
            continue
        name = line[:62].strip()
        form = line[62:74].strip()
        rest = line[74:].split()
        if len(rest) < 3:
            continue
        cik, filed, filename = rest[0], rest[1], rest[2]
        if not cik.isdigit():
            continue
        rows.append((name, form, cik, filed, filename))
    return rows


def load_quarter(year, quarter, refresh=False):
    path = INDEX_DIR / f"company_{year}_QTR{quarter}.idx"
    if refresh and path.exists():
        path.unlink()

    def fetch():
        from src.crispdm.sec_client import SEC_SESSION

        response = SEC_SESSION.get(index_url(year, quarter), timeout=(10, 60))
        response.raise_for_status()
        return response.text

    return cached_text(path, fetch)


def collect_issuers(start_year, end_year, refresh=False, log=print):
    issuers = {}
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            if year == end_year and quarter > 4:
                continue
            try:
                raw = load_quarter(year, quarter, refresh=refresh)
            except Exception as err:
                log(f"  {year} QTR{quarter}: index unavailable ({err})")
                continue
            rows = parse_company_index(raw)
            kept = 0
            for name, form, cik, filed, _filename in rows:
                if form not in OPERATING_FORMS:
                    continue
                key = cik.zfill(10)
                entry = issuers.setdefault(
                    key,
                    {
                        "cik": key,
                        "company_name": name,
                        "first_filing": filed,
                        "last_filing": filed,
                        "last_form": form,
                        "forms": set(),
                    },
                )
                entry["forms"].add(form)
                if filed < entry["first_filing"]:
                    entry["first_filing"] = filed
                if filed > entry["last_filing"]:
                    entry["last_filing"] = filed
                    entry["last_form"] = form
                    entry["company_name"] = name
                kept += 1
            log(f"  {year} QTR{quarter}: {kept:,} operating-company filings")
    return issuers


def warehouse_issuers():
    with engine.connect() as c:
        issuers = {
            str(row[0]).zfill(10)
            for row in c.execute(text("SELECT cik FROM reference.issuers WHERE cik IS NOT NULL"))
        }
        securities = {}
        for cik, ticker in c.execute(
            text("SELECT cik, ticker FROM reference.securities WHERE cik IS NOT NULL")
        ):
            securities.setdefault(str(cik).zfill(10), []).append(ticker)
    return issuers, securities


def submissions_path(cik):
    return SUBMISSIONS_DIR / f"CIK{cik}.json"


def load_submissions(cik, refresh=False):
    path = submissions_path(cik)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    payload = get_submissions(cik)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def recent_filings(payload):
    filings = (payload or {}).get("filings", {}).get("recent", {}) or {}
    if not all(key in filings for key in ("accessionNumber", "form", "primaryDocument")):
        return []
    length = len(filings["form"])
    return [
        {
            "accession_no": filings["accessionNumber"][i],
            "filing_date": filings["filingDate"][i],
            "form": filings["form"][i],
            "primary_document": filings["primaryDocument"][i],
        }
        for i in range(length)
    ]


def candidate_filings(filings, limit=6):
    dated = [row for row in filings if row["form"] in COVER_FORMS]
    if not dated:
        return []
    dated.sort(key=lambda row: row["filing_date"], reverse=True)
    dated.sort(key=lambda row: COVER_FORMS[row["form"]])
    return dated[:limit]


def resolved_path(cik):
    return RESOLVED_DIR / f"CIK{cik}.json"


def resolve_issuer(cik, refresh=False, attempts=4, operating_only=False):
    cached = resolved_path(cik)
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))

    payload = load_submissions(cik, refresh=refresh)
    name = (payload or {}).get("name")
    entity_type = (payload or {}).get("entityType") or ""
    if operating_only and entity_type != "operating":
        result = {
            "cik": cik,
            "company_name": name,
            "entity_type": entity_type,
            "sic": (payload or {}).get("sic") or "",
            "pairs": [],
            "form": "",
            "filing_date": "",
            "accession_no": "",
        }
        result_path = resolved_path(cik)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result
    pairs = []
    used = None
    for filing in candidate_filings(recent_filings(payload), limit=attempts):
        try:
            url, xml, _hash = filing_instance_url(
                cik, filing["accession_no"], filing["primary_document"]
            )
        except Exception:  # noqa: S112 - best-effort fetch; try the next filing
            continue
        if not xml:
            continue
        found, _titles = parse_dei_instrument_titles(xml)
        clean = [
            (symbol.strip().upper(), title.strip())
            for symbol, title in found
            if symbol and symbol.strip()
        ]
        if clean:
            pairs = clean
            used = filing
            break

    if not pairs:
        for ticker in (payload or {}).get("tickers") or []:
            if ticker:
                pairs.append((str(ticker).strip().upper(), ""))
        if pairs:
            used = {"form": "submissions_tickers", "filing_date": "", "accession_no": ""}

    result = {
        "cik": cik,
        "company_name": name,
        "entity_type": (payload or {}).get("entityType") or "",
        "sic": (payload or {}).get("sic") or "",
        "pairs": [
            {
                "ticker": ticker,
                "title": title,
                "security_type": classify_security_type(title or ticker),
            }
            for ticker, title in pairs
        ],
        "form": (used or {}).get("form", ""),
        "filing_date": (used or {}).get("filing_date", ""),
        "accession_no": (used or {}).get("accession_no", ""),
    }
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(result), encoding="utf-8")
    return result


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cik",
        "company_name",
        "ticker",
        "title",
        "security_type",
        "form_type",
        "filing_date",
        "accession_no",
        "source",
        "entity_type",
        "sic",
        "in_warehouse",
        "reference_tickers",
        "first_filing",
        "last_filing",
        "last_form",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument(
        "--resolve-limit", type=int, default=None, help="Resolve at most N missing issuers"
    )
    parser.add_argument(
        "--ciks", type=str, default=None, help="Comma-separated CIKs to resolve regardless of limit"
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore caches and refetch")
    parser.add_argument(
        "--until",
        type=str,
        default="2025-12-31",
        help="Only issuers whose last operating filing is on or before this date "
        "(default excludes current-year new listings)",
    )
    parser.add_argument(
        "--annual-only",
        action="store_true",
        help="Only issuers with an annual report in the window",
    )
    parser.add_argument(
        "--operating-only",
        action="store_true",
        help="Skip filers whose SEC entity type is not operating",
    )
    parser.add_argument("--csv", type=Path, default=OUTPUT)
    args = parser.parse_args()

    print(f"Collecting operating-company filings, {args.start_year}-{args.end_year}")
    issuers = collect_issuers(args.start_year, args.end_year, refresh=args.refresh)
    known, securities = warehouse_issuers()
    missing = {cik: value for cik, value in issuers.items() if cik not in known}
    print(f"EDGAR operating issuers: {len(issuers):,}")
    print(f"In warehouse: {len(issuers) - len(missing):,}; missing: {len(missing):,}")

    targets = [row for row in missing.values() if row["last_filing"] <= args.until]
    if args.annual_only:
        targets = [
            row
            for row in targets
            if any(form.startswith(("10-K", "20-F", "40-F")) for form in row["forms"])
        ]
    targets.sort(key=lambda row: row["last_filing"], reverse=True)
    if args.ciks:
        wanted = {cik.strip().zfill(10) for cik in args.ciks.split(",") if cik.strip()}
        targets = [row for row in targets if row["cik"] in wanted]
        absent = wanted - {row["cik"] for row in targets}
        if absent:
            print(f"  CIKs not found in the EDGAR index: {sorted(absent)}")
    elif args.resolve_limit:
        targets = targets[: args.resolve_limit]

    rows = []
    resolved = 0
    no_ticker = 0
    for position, issuer in enumerate(targets, start=1):
        cik = issuer["cik"]
        try:
            result = resolve_issuer(cik, refresh=args.refresh, operating_only=args.operating_only)
        except Exception as err:
            print(f"  {cik}: resolve failed ({err})")
            continue
        if args.operating_only and result.get("entity_type") != "operating":
            continue
        if not result["pairs"]:
            no_ticker += 1
            continue
        resolved += 1
        for pair in result["pairs"]:
            rows.append(
                {
                    "cik": cik,
                    "company_name": issuer["company_name"] or result.get("company_name") or "",
                    "ticker": pair["ticker"],
                    "title": pair["title"],
                    "security_type": pair["security_type"],
                    "form_type": result["form"],
                    "filing_date": result["filing_date"],
                    "accession_no": result["accession_no"],
                    "source": "sec_cover_page",
                    "entity_type": result.get("entity_type", ""),
                    "sic": result.get("sic", ""),
                    "in_warehouse": False,
                    "reference_tickers": "",
                    "first_filing": issuer["first_filing"],
                    "last_filing": issuer["last_filing"],
                    "last_form": issuer["last_form"],
                }
            )
        if position % 50 == 0:
            print(
                f"  {position}/{len(targets)} issuers resolved ({resolved} with a ticker, {no_ticker} without)"
            )

    for cik, value in sorted(issuers.items()):
        if cik not in known:
            continue
        for ticker in securities.get(cik, []):
            rows.append(
                {
                    "cik": cik,
                    "company_name": value["company_name"],
                    "ticker": ticker,
                    "title": "",
                    "security_type": "",
                    "form_type": "",
                    "filing_date": "",
                    "accession_no": "",
                    "source": "warehouse",
                    "in_warehouse": True,
                    "reference_tickers": ";".join(securities.get(cik, [])),
                    "first_filing": value["first_filing"],
                    "last_filing": value["last_filing"],
                    "last_form": value["last_form"],
                }
            )

    write_csv(rows, args.csv)
    print(f"Wrote {len(rows):,} rows to {args.csv}")
    print(f"Resolved {resolved:,} missing issuers; {no_ticker:,} had no recoverable ticker")


if __name__ == "__main__":
    main()
