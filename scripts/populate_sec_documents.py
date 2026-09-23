"""Index all XBRL concepts already stored in ``raw.companyfacts``.

The loader uses active reference securities (dividend-flagged by default) and
upserts the discovered concepts into ``raw.sec_documents.concept_groups`` for
downstream feature processing, without making any new SEC requests.

Run from the repository root:
    python3 scripts/populate_sec_documents.py
    python3 scripts/populate_sec_documents.py --tickers AAPL,MSFT
    python3 scripts/populate_sec_documents.py --all   # include non-dividend payers
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine


CONCEPT_GROUPS = (
    "dividends",
    "earnings",
    "cash_flow",
    "balance_sheet",
    "debt",
    "tax",
    "share_counts",
)


def normalize_cik(cik):
    """Return a CIK in SEC's ten-digit zero-padded format."""
    return str(int(str(cik).strip())).zfill(10)


def classify_concept(concept_name):
    """Return the requested groups matching one XBRL concept name."""
    name = concept_name.lower()
    groups = []
    if "dividend" in name:
        groups.append("dividends")
    if any(token in name for token in ("earnings", "income", "eps", "profit", "margin")):
        groups.append("earnings")
    if any(token in name for token in ("cashflow", "cash_flow", "operatingcashflow", "freecashflow", "fcf")):
        groups.append("cash_flow")
    if any(token in name for token in ("asset", "liability", "equity", "balance", "shareholder")):
        groups.append("balance_sheet")
    if any(token in name for token in ("debt", "borrow", "liability", "notespayable", "longtermdebt")):
        groups.append("debt")
    if "tax" in name:
        groups.append("tax")
    if any(token in name for token in ("share", "shares", "stock", "commonstock", "treasurystock")):
        groups.append("share_counts")
    return groups


def extract_company_concepts(raw_payload):
    """Extract all taxonomy concepts and requested concept groups from a payload."""
    if not isinstance(raw_payload, dict):
        return {"all_concepts": [], **{group: [] for group in CONCEPT_GROUPS}}

    taxonomies = raw_payload.get("facts", raw_payload)
    if not isinstance(taxonomies, dict):
        taxonomies = {}

    all_concepts = []
    groups = {group: [] for group in CONCEPT_GROUPS}
    for taxonomy, concepts in taxonomies.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name in concepts:
            qualified_name = f"{taxonomy}:{concept_name}"
            all_concepts.append(qualified_name)
            for group in classify_concept(concept_name):
                groups[group].append(qualified_name)

    groups["all_concepts"] = sorted(set(all_concepts))
    for group in CONCEPT_GROUPS:
        groups[group] = sorted(set(groups[group]))
    return groups


def load_companyfacts(conn, tickers=None, dividend_only=True):
    """Load companyfacts rows for active securities (dividend payers by default).

    ``raw.companyfacts`` is keyed by issuer CIK (one payload per CIK shared by
    all of the issuer's listed securities), so the join runs through
    ``reference.securities.cik``.
    """
    params = {}
    clauses = ["s.active = TRUE", "NULLIF(cf.cik, '') IS NOT NULL"]
    if dividend_only:
        clauses.append("s.dividend = TRUE")
    ticker_clause = ""
    if tickers:
        ticker_clause = "AND UPPER(s.ticker) = ANY(:tickers)"
        params["tickers"] = [ticker.upper() for ticker in tickers]

    return conn.execute(text(f"""
        SELECT s.security_id, cf.cik, cf.raw_payload, s.ticker
        FROM raw.companyfacts cf
        JOIN reference.securities s ON s.cik = cf.cik
        WHERE {' AND '.join(clauses)}
          {ticker_clause}
        ORDER BY s.ticker
    """), params).mappings().all()


def populate_concept_groups(tickers=None, dividend_only=True):
    """Upsert raw.sec_documents concept-groups from stored raw.companyfacts payloads."""
    updated = 0
    errors = 0
    with engine.begin() as conn:
        rows = load_companyfacts(conn, tickers=tickers, dividend_only=dividend_only)
        for row in rows:
            try:
                groups = extract_company_concepts(row["raw_payload"])
                conn.execute(text("""
                    INSERT INTO raw.sec_documents
                        (security_id, cik, concept_groups, content_hash, retrieved_at)
                    VALUES (:security_id, :cik,
                            CAST(:concept_groups AS jsonb),
                            :content_hash, now())
                    ON CONFLICT (security_id) WHERE security_id IS NOT NULL DO UPDATE SET
                        cik = EXCLUDED.cik,
                        concept_groups = EXCLUDED.concept_groups,
                        content_hash = EXCLUDED.content_hash,
                        retrieved_at = now()
                """), {
                    "security_id": row["security_id"],
                    "cik": row["cik"],
                    "concept_groups": json.dumps(groups),
                    "content_hash": hashlib.sha256(
                        json.dumps(groups, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                })
                updated += 1
            except Exception as exc:
                errors += 1
                print(f"Error processing {row['ticker']} (CIK {row['cik']}): {exc}")

    print(f"Completed: rows={len(rows)}, updated={updated}, errors={errors}")
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include non-dividend securities (by default only dividend payers are indexed)",
    )
    args = parser.parse_args()
    tickers = [value.strip().upper() for value in args.tickers.split(",") if value.strip()] if args.tickers else None
    try:
        populate_concept_groups(tickers=tickers, dividend_only=not args.all)
    except Exception as exc:
        print(f"SEC concept processing failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
