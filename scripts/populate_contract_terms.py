"""Mine preferred-stock liquidation/preference and call-price (redemption)
contractual clauses from narrative SEC filings.

XBRL companyfacts tags stop where the contract starts: the per-share
Liquidation Preference and the Optional Redemption (call) price are defined in

1. the Certificate of Designation - Form 8-K, Exhibit 3.1 / 3.2
   (Item 5.03 / 3.03 filings: "Liquidation Preference", "Optional
   Redemption", "Redeemable at the option", "$25.00 per share"), and
2. the prospectus / prospectus supplement - Form 424B5 / 424B3, or the
   S-1 / S-3 registration statement ("Summary of the Offering",
   "Description of (Series X) Preferred Stock", "Liquidation Preference /
   Liquidation Rights", "Redemption / Optional Redemption").

For each active preferred security the script prefers the 8-K Certificate of
Designation (the governing document) and falls back to the most recent
prospectus supplement. Documents are cached in raw.contract_documents and the
parsed clauses land in preferred.contract_terms with the source document +
exact snippet as evidence.

Usage:
    python -m scripts.populate_contract_terms
    python -m scripts.populate_contract_terms --tickers ACR-PD,ACR-PC
    python -m scripts.populate_contract_terms --cik 0001332551
    python -m scripts.populate_contract_terms --max 20
    python -m scripts.populate_contract_terms --discover   # report planned sources without fetching
    python -m scripts.populate_contract_terms --force      # re-fetch stored documents

SEC_ETL_OFFLINE=1 makes the run consume only raw.contract_documents already
stored (no data.sec.gov requests).
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.doc_clauses import (
    extract_liquidation_preference,
    extract_redemption,
    html_to_text,
)
from src.crispdm.sec_client import (
    SEC_SESSION,
    HEADERS,
    fetch_archive_index,
    fetch_filing,
    filing_url,
)


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()

CERTIFICATE_FORMS = ("8-K", "8-K/A")
PROSPECTUS_FORMS = (
    "424B5", "424B5/A", "424B3", "424B3/A", "424B7", "424B4",
    "424B2", "424B1", "S-1", "S-1/A", "S-3", "S-3/A",
)
PROSPECTUS_PRIORITY = {
    form: index for index, form in enumerate((
        "424B5", "424B5/A", "424B3", "424B3/A", "424B7", "424B4",
        "424B2", "424B1", "S-1/A", "S-1", "S-3/A", "S-3",
    ))
}

EXHIBIT_RE = re.compile(
    r"\bex[-_.]?3[-_.]?[12]\b|\b3[-_.]?[12]\b|certificate\s+of\s+designation",
    re.IGNORECASE,
)

# SEC asks for <=10 requests/second; a modest gap keeps bulk runs polite.
REQUEST_DELAY = float(os.environ.get("SEC_REQUEST_DELAY", ".25"))


def normalize_cik(cik):
    return str(int(str(cik).strip())).zfill(10)


def _filings(submissions_payload, forms):
    filings = (submissions_payload or {}).get("filings", {}).get("recent", {})
    keys = ["accessionNumber", "form", "filingDate", "primaryDocument", "items"]
    index = range(len(filings.get("accessionNumber") or []))
    rows = []
    for i in index:
        def value(key, i=i):
            seq = filings.get(key) or []
            return seq[i] if i < len(seq) else None
        if not value("accessionNumber"):
            continue
        entry = {key: value(key) for key in keys}
        entry["form"] = str(entry["form"] or "").upper()
        if entry["form"] in forms:
            rows.append(entry)
    rows.sort(key=lambda item: item["filingDate"] or "", reverse=True)
    return rows


# An 8-K announcing a Certificate of Designation is filed under Item 3.03
# (Material Modification to Rights of Security Holders) and/or 5.03
# (Amendments to Articles of Incorporation or Bylaws).
COD_ITEMS = ("3.03", "5.03")


def _filing_items(filing):
    value = filing.get("items")
    if isinstance(value, str):
        return [part.strip() for part in value.replace(",", " ").split() if part.strip()]
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def pick_prospectus_file(submissions_payload):
    """Most recent prospectus supplement / registration statement with a primary document."""
    for filing in _filings(submissions_payload, PROSPECTUS_FORMS):
        if filing.get("primaryDocument"):
            return filing
    return None


def pick_certificate_filings(submissions_payload, limit=3):
    """Recent 8-Ks that may carry a Certificate of Designation exhibit.

    COD announcements are Item 3.03 / 5.03 filings, so those are tried first;
    any other recent 8-K is kept as a fallback (item codes are occasionally
    missing or abbreviated).
    """
    filings = _filings(submissions_payload, CERTIFICATE_FORMS)
    cod_filings = [f for f in filings
                   if set(_filing_items(f)) & set(COD_ITEMS)]
    return (cod_filings or filings)[:limit]


# The index metadata for an Exhibit 3.1 tells us nothing about whether the
# exhibit is a Certificate of Designation (it can also be a charter/bylaws
# amendment), so an exhibit only counts once its content shows the operative
# contractual language.
COD_SIGNALS_RE = re.compile(
    r"liquidation\s+preference|optional\s+redemption|redeemable\s+at\s+(?:our|the)\s+option"
    r"|at\s+(?:our|the\s+(?:company|issuer)(?:['\u2019]s)?)\s+option",
    re.IGNORECASE,
)


def find_certificate_exhibit(cik, accession_no):
    """Find the Certificate of Designation exhibit file (3.1/3.2) in an 8-K.

    Candidates are ranked by how strongly the index describes a Certificate of
    Designation (vs. an Articles-of-Amendment / bylaws exhibit). A rank of 1
    and below is not trusted; the fetching caller additionally confirms the
    content before accepting a candidate.
    """
    try:
        items = fetch_archive_index(cik, accession_no)
    except Exception:
        return None
    scored = []
    for description, name, item_type in items:
        if not name.lower().endswith((".htm", ".html", ".txt")):
            continue
        haystack = f"{item_type} {description} {name}".lower()
        if not EXHIBIT_RE.search(haystack):
            continue
        score = 0
        if "certificate of designation" in haystack:
            score += 5
        elif "certificate" in haystack:
            score += 2
        if re.search(r"\bex[-_.]?3[-_.]?[12]\b", haystack):
            score += 2
        if any(term in haystack for term in (
                "articles of amendment", "amendment to the", "bylaws",
                "ownership limit", "share ownership", "purchase contract",
                "waiver", "supplemental indenture")):
            score -= 5
        scored.append((score, name, item_type))
    scored.sort(key=lambda item: item[0], reverse=True)
    for score, name, item_type in scored:
        if score >= 2:
            return {"name": name, "exhibit_type": item_type}
    return None


def _document_found(conn, security_id, form_type, accession_no, primary_document):
    return conn.execute(text(
        "SELECT document_id FROM raw.contract_documents "
        "WHERE security_id = :sid AND form_type = :form "
        "AND accession_no = :acc AND primary_document = :doc"
    ), {"sid": security_id, "form": form_type, "acc": accession_no,
        "doc": primary_document}).scalar()


def _store_document(conn, security_id, cik, form_type, filing_date, accession_no,
                    primary_document, exhibit_type, source_url, raw_text, doc_hash):
    existing = _document_found(conn, security_id, form_type, accession_no,
                               primary_document)
    if existing:
        return existing, False
    return conn.execute(text("""
        INSERT INTO raw.contract_documents
            (security_id, cik, form_type, filing_date, accession_no,
             primary_document, exhibit_type, source_url, raw_text,
             content_hash, retrieved_at)
        VALUES (:sid, :cik, :form, :filing_date, :acc, :doc,
                :exhibit, :url, :raw_text, :hash, now())
        RETURNING document_id
    """), {
        "sid": security_id, "cik": cik, "form": form_type,
        "filing_date": filing_date, "acc": accession_no, "doc": primary_document,
        "exhibit": exhibit_type, "url": source_url, "raw_text": raw_text,
        "hash": doc_hash,
    }).scalar(), True


def fetch_source_documents(conn, security, force=False):
    """Fetch + cache the governing documents for a security; return doc rows.

    Prefers the 8-K Certificate of Designation (Exhibit 3.1/3.2); falls back to
    the most recent prospectus supplement.
    """
    cik = security["cik"]
    submissions = security.get("raw_payload")
    docs = []

    certificate_filings = pick_certificate_filings(submissions)
    for candidate in certificate_filings:
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)
        exhibit = find_certificate_exhibit(cik, candidate["accessionNumber"])
        if not exhibit:
            continue
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
               f"{candidate['accessionNumber'].replace('-', '')}/{exhibit['name']}")
        try:
            raw_text, doc_hash = fetch_filing(url)
        except Exception:
            continue
        normalized = html_to_text(raw_text)
        # The index can call an Articles-of-Amendment exhibit "3.1"; only keep
        # exhibits whose content actually carries the contractual language.
        if not COD_SIGNALS_RE.search(normalized):
            continue
        document_id, _new = _store_document(
            conn, security["security_id"], cik, candidate["form"],
            candidate.get("filingDate"), candidate["accessionNumber"],
            exhibit["name"], exhibit["exhibit_type"], url, normalized, doc_hash,
        )
        docs.append({"document_id": document_id,
                     "form_type": candidate["form"],
                     "exhibit_type": exhibit["exhibit_type"],
                     "raw_text": normalized})
        break

    prospectus = pick_prospectus_file(submissions)
    if prospectus:
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)
        url = filing_url(cik, prospectus["accessionNumber"],
                         prospectus["primaryDocument"])
        raw_text, doc_hash = fetch_filing(url)
        normalized = html_to_text(raw_text)
        document_id, _new = _store_document(
            conn, security["security_id"], cik, prospectus["form"],
            prospectus.get("filingDate"), prospectus["accessionNumber"],
            prospectus["primaryDocument"], None, url, normalized, doc_hash,
        )
        docs.append({"document_id": document_id,
                     "form_type": prospectus["form"],
                     "exhibit_type": None,
                     "raw_text": normalized})
    return docs


def load_stored_documents(conn, security_id):
    rows = conn.execute(text("""
        SELECT document_id, form_type, exhibit_type, raw_text
        FROM raw.contract_documents
        WHERE security_id = :sid ORDER BY document_id
    """), {"sid": security_id}).mappings().all()
    return [
        {"document_id": row["document_id"], "form_type": row["form_type"],
         "exhibit_type": row["exhibit_type"], "raw_text": row["raw_text"]}
        for row in rows
    ]


def extract_from_documents(docs, series_pattern=None):
    """Mine clauses across the fetched documents; prefer the certificate.

    ``series_pattern`` (from :func:`series_pattern_from_security`) scopes every
    extractor to the passages that mention THIS series, so a combined
    prospectus covering Series A and Series B produces series-accurate terms
    instead of whichever section appears first.
    """
    results = []
    for doc in docs:
        text = doc.get("raw_text") or ""
        liquidation = extract_liquidation_preference(text, series_pattern)
        redemption = extract_redemption(text, series_pattern)
        results.append({
            "document_id": doc["document_id"],
            "form_type": doc["form_type"],
            "exhibit_type": doc["exhibit_type"],
            "liquidation": liquidation,
            "redemption": redemption,
        })

    def is_certificate(result):
        return bool(result["exhibit_type"]) or result["form_type"] in CERTIFICATE_FORMS

    results.sort(key=lambda result: (is_certificate(result), result["document_id"]),
                 reverse=True)

    liquidation_result = next((r for r in results if r["liquidation"]), None)
    redemption_result = next((r for r in results if r["redemption"]), None)
    source = (liquidation_result or redemption_result
              or (next((r for r in results if is_certificate(r)), None)
                  or (results[0] if results else None)))

    sections = []
    if liquidation_result:
        liquidation = liquidation_result["liquidation"]
        sections.append({"clause": "liquidation_preference",
                         "source_document_id": liquidation_result["document_id"],
                         "form_type": liquidation_result["form_type"],
                         "exhibit_type": liquidation_result["exhibit_type"],
                         "heading": liquidation.get("heading"),
                         "snippet": liquidation.get("snippet"),
                         "match": liquidation.get("match"),
                         "amount": str(liquidation["amount"])})
    if redemption_result:
        redemption = redemption_result["redemption"]
        sections.append({"clause": "redemption",
                         "source_document_id": redemption_result["document_id"],
                         "form_type": redemption_result["form_type"],
                         "exhibit_type": redemption_result["exhibit_type"],
                         "heading": redemption.get("heading"),
                         "snippet": redemption.get("snippet"),
                         "match": redemption.get("match"),
                         "first_call_date": redemption.get("first_call_date"),
                         "call_price": (str(redemption["call_price"])
                                        if redemption.get("call_price") is not None else None)})

    redemption = redemption_result["redemption"] if redemption_result else None
    liquidation = liquidation_result["liquidation"] if liquidation_result else None
    confidence_values = [
        value for value in (
            (liquidation or {}).get("confidence"),
            (redemption or {}).get("confidence"),
        ) if value is not None
    ]
    return {
        "liquidation_preference": (liquidation["amount"] if liquidation else None),
        "call_price": (redemption["call_price"] if redemption else None),
        "first_call_date": (redemption["first_call_date"] if redemption else None),
        "redemption_schedule": (redemption["schedule"] if redemption else []),
        "optional_redemption": bool(redemption and redemption["optional"]),
        "source_document_id": (source["document_id"] if source else None),
        "sections": sections,
        "confidence": (round(sum(confidence_values) / len(confidence_values), 2)
                       if confidence_values else None),
    }


def series_pattern_from_security(security):
    """Regex anchoring how this preferred series is named in filings.

    Uses the "Series <letter>" token from the security name (and, failing that,
    the single series letter carried by the ticker symbol, e.g. the D in
    ACR-PD) plus the coupon rate when present, so per-series passages inside a
    combined prospectus can be isolated.
    """
    name = security.get("security_name") or ""
    ticker = (security.get("ticker") or "").upper()
    letters = []
    match = re.search(r"\bSeries\s+([A-Za-z0-9]+)\b", name)
    if match:
        letters.append(match.group(1))
    suffix = ticker.split("-")[-1] if "-" in ticker else ""
    if suffix and suffix != "PR":
        if suffix.upper().startswith("PR") and len(suffix) == 3:
            letters.append(suffix[-1])
        elif len(suffix) <= 2 and suffix.isalpha():
            letters.append(suffix[-1])
    if not letters:
        return None
    letters = list(dict.fromkeys(letters))
    rate = re.search(r"(\d+(?:\.\d+)?)\s*%", name)
    tokens = letters + ([rate.group(1)] if rate else [])
    pattern = (r"\bseries\s*[-.]?\s*(?:" + "|".join(re.escape(token) for token in tokens)
               + r")\b")
    single = [letter for letter in letters if len(letter) <= 2 and \
              not re.search(r"\d", letter)]
    if single:
        pattern += (r"|\b(?:" + "|".join(re.escape(letter) for letter in single)
                    + r")\s+(?:cumulative\s+)?(?:fixed\s*-?\s*to\s*-?\s*floating\s+)?"
                      r"(?:preferred|redeemable)")
    return re.compile(pattern, re.IGNORECASE)


def load_preferred_securities(conn, tickers=None, cik=None, limit=None):
    clauses = ["s.active = TRUE", "LOWER(s.security_type) IN ('preferred', 'preferred stock')"]
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [t.upper() for t in tickers]
    if cik:
        clauses.append("s.cik = :cik")
        params["cik"] = normalize_cik(cik)
    where = " AND ".join(clauses)
    limit_sql = " LIMIT :limit" if limit else ""
    return conn.execute(text(f"""
        SELECT s.security_id, s.ticker, s.cik, s.security_name,
               sub.raw_payload
        FROM reference.securities s
        JOIN raw.sec_submissions sub ON sub.cik = s.cik
        WHERE {where}
        ORDER BY s.ticker
        {limit_sql}
    """), {**params, **({"limit": limit} if limit else {})}).mappings().all()


def populate_contract_terms(tickers=None, cik=None, limit=None, force=False,
                            discover_only=False):
    """Run the mine: fetch/load documents, extract clauses, upsert terms."""
    processed = errors = 0
    updated = 0
    with engine.begin() as conn:
        securities = load_preferred_securities(conn, tickers=tickers, cik=cik,
                                               limit=limit)
        for security in securities:
            try:
                if discover_only:
                    certs = pick_certificate_filings(security["raw_payload"])
                    prospectus = pick_prospectus_file(security["raw_payload"])
                    print(f"{security['ticker']}: 8-K cert candidates="
                          f"{[c['accessionNumber'] for c in certs]} "
                          f"prospectus={prospectus and prospectus['accessionNumber']}")
                    continue

                if OFFLINE_ON:
                    docs = load_stored_documents(conn, security["security_id"])
                else:
                    docs = fetch_source_documents(conn, security, force=force)
                if not docs:
                    if not OFFLINE_ON:
                        print(f"  No source documents for {security['ticker']}")
                    processed += 1
                    continue

                terms = extract_from_documents(
                    docs, series_pattern=series_pattern_from_security(security)
                )
                if terms["liquidation_preference"] is None and terms["call_price"] is None:
                    if not OFFLINE_ON:
                        print(f"  No liquidation/redemption clause found for "
                              f"{security['ticker']}")
                    processed += 1
                    continue

                _persist_contract_terms(conn, security["security_id"], terms)
                updated += 1
                processed += 1
                if updated % 50 == 0:
                    print(f"  Updated {updated} securities...")
            except Exception as exc:
                errors += 1
                if errors <= 10:
                    print(f"  Error {security['ticker']}: {exc}")

    print(f"Completed: processed={processed}, updated={updated}, errors={errors}")
    return updated


def _persist_contract_terms(conn, security_id, terms):
    conn.execute(text("""
        INSERT INTO preferred.contract_terms
            (security_id, liquidation_preference, call_price, first_call_date,
             redemption_schedule, optional_redemption, source_document_id,
             sections, confidence, updated_at)
        VALUES (:sid, :liq, :call, :date, CAST(:schedule AS jsonb),
                :optional, :doc_id, CAST(:sections AS jsonb), :confidence, now())
        ON CONFLICT (security_id) DO UPDATE SET
            liquidation_preference = EXCLUDED.liquidation_preference,
            call_price = EXCLUDED.call_price,
            first_call_date = EXCLUDED.first_call_date,
            redemption_schedule = EXCLUDED.redemption_schedule,
            optional_redemption = EXCLUDED.optional_redemption,
            source_document_id = EXCLUDED.source_document_id,
            sections = EXCLUDED.sections,
            confidence = EXCLUDED.confidence,
            updated_at = now()
    """), {
        "sid": security_id,
        "liq": terms["liquidation_preference"],
        "call": terms["call_price"],
        "date": terms["first_call_date"],
        "schedule": json.dumps(terms["redemption_schedule"] or []),
        "optional": terms["optional_redemption"],
        "doc_id": terms["source_document_id"],
        "sections": json.dumps(terms["sections"]),
        "confidence": terms["confidence"],
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument("--cik", help="Single issuer CIK (10-digit form optional)")
    parser.add_argument("--max", type=int, default=None,
                        help="Limit to the first N preferred securities")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch documents even when already cached")
    parser.add_argument("--discover", action="store_true",
                        help="Report planned document sources without fetching")
    args = parser.parse_args()

    tickers = [value.strip().upper() for value in args.tickers.split(",")
               if value.strip()] if args.tickers else None
    try:
        populate_contract_terms(
            tickers=tickers, cik=args.cik, limit=args.max, force=args.force,
            discover_only=args.discover,
        )
    except Exception as exc:
        print(f"contract terms ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())