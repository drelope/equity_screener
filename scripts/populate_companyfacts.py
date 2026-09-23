"""Download SEC submissions history, XBRL company facts, and taxonomy data.

By default this populates raw.sec_submissions and raw.companyfacts for the
dividend universe (active securities flagged ``dividend = TRUE``). With
``--preferred-facts`` it targets the preferred-stock securities listed in
raw.ticker_profile instead, so their XBRL company facts are available for the
preferred.security_terms enrichment.

With ``--preferred-taxonomy`` it uses the SEC XBRL Data API ``companyconcept``
endpoint to download taxonomy-scoped facts (``us-gaap``, ``ifrs-full``, ``dei``,
``srt``, ...) for every active preferred stock in reference.securities and
stores them in raw.company_taxonomy. Per-concept 404s (a company simply did
not report that tag) are skipped, so only concepts the issuer actually filed
are persisted.

Usage:
    python -m scripts.populate_companyfacts [--tickers SYMBOL,SYMBOL,...] [--all] [--max-ciks N]
    python -m scripts.populate_companyfacts --preferred-facts [--tickers SYMBOL,...] [--max-ciks N]
    python -m scripts.populate_companyfacts --preferred-taxonomy [--tickers SYMBOL,...]
    python -m scripts.populate_companyfacts --preferred-taxonomy --taxonomies us-gaap,dei,srt
    python -m scripts.populate_companyfacts --preferred
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.sec_client import (
    classify_companyfacts,
    get_company_tickers,
    get_companyconcept,
    get_companyfacts_concepts,
    get_submissions,
)
from src.crispdm.xbrl_tags import (
    DEI_TAXONOMY_CONCEPTS,
    PREFERRED_STOCK_TAXONOMY_CONCEPTS,
)


# Preferred-stock concepts fetched per taxonomy via the XBRL Data API
# companyconcept endpoint. Each name has been verified against the live SEC
# taxonomy; concepts an individual issuer never filed return 404 and are
# skipped. ``ifrs-full`` and ``srt`` are valid taxonomies but expose no
# preferred-stock facts, so they are only requested when a caller passes them
# explicitly via ``--taxonomies``. The tag sets themselves are canonicalised in
# ``src.crispdm.xbrl_tags``.
PREFERRED_TAXONOMY_CONCEPTS = {
    "us-gaap": list(PREFERRED_STOCK_TAXONOMY_CONCEPTS),
    "dei": list(DEI_TAXONOMY_CONCEPTS),
    # Supported SEC taxonomies with no configured preferred-stock concepts.
    "ifrs-full": [],
    "srt": [],
}

def normalize_cik(cik):
    return str(int(str(cik).strip())).zfill(10)


def payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_securities(conn, tickers=None, dividend_only=True):
    """Active securities to ingest.

    Defaults to ``dividend = TRUE`` so SEC submissions and XBRL companyfacts
    are only downloaded for the dividend universe, never for non-payers.
    """
    clauses = ["s.active = TRUE"]
    params = {}
    if dividend_only:
        clauses.append("s.dividend = TRUE")
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]

    return conn.execute(text(f"""
        SELECT s.security_id, s.ticker
        FROM reference.securities s
        WHERE {' AND '.join(clauses)}
        ORDER BY s.ticker
    """), params).mappings().all()


def load_companyfacts_targets(conn, tickers=None, dividend_only=True):
    """Combine the audited dividend universe with preferred profile targets.

    A profile is the durable handoff for preferred dividend securities. Keep
    those rows in the Company Facts target set even when the issuer's SEC
    Company Facts endpoint is unavailable during reference classification.
    """
    targets = {
        row["ticker"].upper(): row
        for row in load_securities(conn, tickers=tickers, dividend_only=dividend_only)
    }
    for row in load_ticker_profile_targets(conn, tickers=tickers):
        targets.setdefault(row["ticker"].upper(), row)
    return list(targets.values())


def load_preferred_securities(conn, tickers=None):
    """Active preferred-stock targets direct from reference.securities.

    Unlike ``load_ticker_profile_targets`` (which reads raw.ticker_profile),
    this resolves the target set from ``reference.securities`` itself, where
    preferred series are flagged ``security_type = 'preferred stock'``.
    """
    clauses = [
        "s.security_type = 'preferred stock'",
        "s.active = TRUE",
        "NULLIF(s.cik, '') IS NOT NULL",
    ]
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]

    return conn.execute(text(f"""
        SELECT s.security_id, s.ticker, s.cik,
               s.security_name AS title
        FROM reference.securities s
        WHERE {' AND '.join(clauses)}
        ORDER BY s.ticker
    """), params).mappings().all()


def load_ticker_profile_targets(conn, tickers=None):
    """Preferred-stock targets from raw.ticker_profile.

    Returns one row per ticker recorded in raw.ticker_profile whose security is
    preferred stock (either the profile or the linked reference.securities row
    carries a preferred-stock type) and that resolves to an SEC CIK.
    """
    clauses = [
        "(UPPER(tp.security_type) LIKE '%PREFERRED%' "
        "OR s.security_type = 'preferred stock')",
        "s.active = TRUE",
        "COALESCE(NULLIF(s.cik, ''), t.cik) IS NOT NULL",
    ]
    params = {}
    if tickers:
        clauses.append("UPPER(tp.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]

    return conn.execute(text(f"""
        SELECT DISTINCT ON (tp.ticker)
               tp.security_id,
               tp.ticker,
               COALESCE(NULLIF(s.cik, ''), t.cik) AS cik,
               COALESCE(s.security_name, t.title, tp.ticker) AS title
        FROM raw.ticker_profile tp
        JOIN reference.securities s ON s.security_id = tp.security_id
        LEFT JOIN raw.company_ticker t ON UPPER(t.ticker) = UPPER(tp.ticker)
        WHERE {' AND '.join(clauses)}
        ORDER BY tp.ticker, s.updated_at DESC NULLS LAST
    """), params).mappings().all()


def populate_preferred_stocks():
    """Create baseline preferred terms from ``reference.securities``."""
    stored = 0

    with engine.begin() as conn:
        securities = conn.execute(text("""
            SELECT security_id, ticker, security_name
            FROM reference.securities
            WHERE active = TRUE
              AND LOWER(security_type) IN ('preferred', 'preferred stock')
            ORDER BY ticker
        """)).mappings().all()

        for security in securities:
            ticker = security["ticker"]
            conn.execute(text("""
                INSERT INTO preferred.security_terms AS existing
                    (security_id, preferred_series, dividend_rate,
                     liquidation_preference, confidence_score, reviewed_by,
                     reviewed_at)
                VALUES (:security_id, :preferred_series, NULL, NULL, NULL,
                        'reference.securities', now())
                ON CONFLICT (security_id) DO UPDATE SET
                    preferred_series = COALESCE(existing.preferred_series,
                                                EXCLUDED.preferred_series),
                    reviewed_by = EXCLUDED.reviewed_by,
                    reviewed_at = EXCLUDED.reviewed_at
            """), {
                "security_id": security["security_id"],
                "preferred_series": security["security_name"] or ticker,
            })
            stored += 1

    print(f"Completed preferred-stock population: {stored} records")
    return stored


def upsert_classification(conn, cik, ticker, companyfacts):
    """Persist the compact per-CIK classification cache.

    The cache lets later stages (populate_reference_tables,
    populate_companyfacts) reuse the class computed from an already-downloaded
    companyfacts payload instead of requesting the full issuer JSON from SEC a
    second (or third) time.
    """
    if companyfacts is None:
        return
    classification = classify_companyfacts(companyfacts)
    conn.execute(text("""
        INSERT INTO raw.company_classification
            (cik, ticker, company_name, security_types, security_titles,
             security_facts, dividend_facts, dividend, status, content_hash,
             retrieved_at)
        VALUES (:cik, :ticker, :company_name, CAST(:security_types AS jsonb),
                CAST(:security_titles AS jsonb), CAST(:security_facts AS jsonb),
                CAST(:dividend_facts AS jsonb),
                :dividend, :status, :content_hash, now())
        ON CONFLICT (cik) DO UPDATE SET
            ticker = EXCLUDED.ticker,
            company_name = EXCLUDED.company_name,
            security_types = EXCLUDED.security_types,
            security_titles = EXCLUDED.security_titles,
            security_facts = EXCLUDED.security_facts,
            dividend_facts = EXCLUDED.dividend_facts,
            dividend = EXCLUDED.dividend,
            status = EXCLUDED.status,
            content_hash = EXCLUDED.content_hash,
            retrieved_at = now()
    """), {
        "cik": cik,
        "ticker": ticker,
        "company_name": companyfacts.get("company"),
        "security_types": json.dumps(classification["security_types"]),
        "security_titles": json.dumps(classification.get("security_titles", [])),
        "security_facts": json.dumps(classification["security_facts"]),
        "dividend_facts": json.dumps(classification["dividend_facts"]),
        "dividend": classification["dividend"],
        "status": classification["status"],
        "content_hash": payload_hash(classification["dividend_facts"]),
    })


def upsert_submissions(conn, cik, title, submissions):
    conn.execute(text("""
        INSERT INTO raw.sec_submissions
            (cik, company_name, raw_payload, content_hash, provider, retrieved_at)
        VALUES (:cik, :company_name, CAST(:raw_payload AS jsonb),
                :content_hash, 'SEC_SUBMISSIONS', :retrieved_at)
        ON CONFLICT (cik) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            raw_payload = EXCLUDED.raw_payload,
            content_hash = EXCLUDED.content_hash,
            provider = EXCLUDED.provider,
            retrieved_at = EXCLUDED.retrieved_at
    """), {
        "cik": cik,
        "company_name": submissions.get("name") or title,
        "raw_payload": json.dumps(submissions),
        "content_hash": payload_hash(submissions),
        "retrieved_at": datetime.now(timezone.utc),
    })


def upsert_companyfacts(conn, cik, companyfacts):
    facts = companyfacts["full_facts"]
    conn.execute(text("""
        INSERT INTO raw.companyfacts
            (cik, company_name, concept_groups, raw_payload,
             content_hash, provider, retrieved_at)
        VALUES (:cik, :company_name, CAST(:concept_groups AS jsonb),
                CAST(:raw_payload AS jsonb), :content_hash, 'SEC_XBRL', :retrieved_at)
        ON CONFLICT (cik) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            concept_groups = EXCLUDED.concept_groups,
            raw_payload = EXCLUDED.raw_payload,
            content_hash = EXCLUDED.content_hash,
            provider = EXCLUDED.provider,
            retrieved_at = EXCLUDED.retrieved_at
    """), {
        "cik": cik,
        "company_name": companyfacts["company"],
        "concept_groups": json.dumps(companyfacts["concept_groups"]),
        "raw_payload": json.dumps(facts),
        "content_hash": payload_hash(facts),
        "retrieved_at": datetime.now(timezone.utc),
    })


def upsert_company_taxonomy(conn, cik, company_name, taxonomy_payload):
    """Store taxonomy-scoped XBRL concept facts for one issuer CIK.

    ``taxonomy_payload`` maps taxonomy name (``us-gaap``, ``dei``, ...) to the
    concept facts that were reported: ``{taxonomy: {concept: {..} }}``. The
    ``taxonomies`` column records which concepts were present per taxonomy; the
    flat preferred-stock tag list is mirrored into ``concept_groups``. One row
    per CIK: every listed security of the issuer shares the payload through
    ``reference.securities.cik``.
    """
    available = {
        taxonomy: sorted(concepts)
        for taxonomy, concepts in taxonomy_payload.items()
    }
    concept_groups = {
        "preferred_stock": sorted(
            {
                concept
                for concepts in available.values()
                for concept in concepts
            }
        )
    }
    conn.execute(text("""
        INSERT INTO raw.company_taxonomy
            (cik, company_name, taxonomies, concept_groups,
             raw_payload, content_hash, provider, retrieved_at)
        VALUES (:cik, :company_name, CAST(:taxonomies AS jsonb),
                CAST(:concept_groups AS jsonb), CAST(:raw_payload AS jsonb),
                :content_hash, 'SEC_XBRL', :retrieved_at)
        ON CONFLICT (cik) DO UPDATE SET
            company_name = EXCLUDED.company_name,
            taxonomies = EXCLUDED.taxonomies,
            concept_groups = EXCLUDED.concept_groups,
            raw_payload = EXCLUDED.raw_payload,
            content_hash = EXCLUDED.content_hash,
            provider = EXCLUDED.provider,
            retrieved_at = EXCLUDED.retrieved_at
    """), {
        "cik": cik,
        "company_name": company_name,
        "taxonomies": json.dumps(available),
        "concept_groups": json.dumps(concept_groups),
        "raw_payload": json.dumps(taxonomy_payload),
        "content_hash": payload_hash(taxonomy_payload),
        "retrieved_at": datetime.now(timezone.utc),
    })


def existing_facts_ciks(conn):
    """CIKs that already have a company facts payload stored.

    Fetches are per-CIK: every preferred series of an issuer shares the same
    SEC companyfacts payload, so the row is keyed by CIK and never copied per
    security. Skipping CIKs already persisted keeps re-runs and overlapping
    pipelines (dividend universe vs preferred set) from downloading the same
    payload twice.
    """
    return {
        row[0]
        for row in conn.execute(text(
            "SELECT DISTINCT cik FROM raw.companyfacts WHERE cik IS NOT NULL"
        ))
    }


def _ingest_cik(conn, cik, linked_entries, stats):
    """Fetch submissions + XBRL company facts once per CIK and store once.

    ``linked_entries`` is a list of ``(ticker, title, security)`` tuples
    sharing the same CIK. The submissions and companyfacts payloads describe
    the ISSUER, so each is inserted as a single CIK-keyed row that every
    listed security of the issuer reads through ``reference.securities.cik``.
    ``stats`` is a mutable dict with the aggregate counters.
    """
    ticker, title, _ = linked_entries[0]

    try:
        stats["fetched"] += 1
        submissions = get_submissions(cik)
        upsert_submissions(conn, cik, title, submissions)
        stats["stored_submissions"] += 1
    except Exception as exc:
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None and exc.response.status_code == 404:
            stats["unavailable"] += 1
        else:
            stats["errors"] += 1
            print(f"Error fetching submissions for {ticker} (CIK {cik}): {exc}")

    try:
        facts = get_companyfacts_concepts(cik)
        upsert_companyfacts(conn, cik, facts)
        stats["stored_facts"] += 1
        upsert_classification(conn, cik, ticker, facts)
    except Exception as exc:
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None and exc.response.status_code == 404:
            stats["unavailable"] += 1
        else:
            stats["errors"] += 1
            print(f"Error fetching companyfacts for {ticker} (CIK {cik}): {exc}")


def populate_companyfacts(tickers=None, dividend_only=True, max_ciks=None):
    """Fetch one submissions and one XBRL payload per unique SEC CIK.

    Only downloads payloads for active securities (dividend-flagged by
    default) so CIKs that never pay a dividend are not fetched from SEC.
    Resumable: CIKs already present in raw.companyfacts are skipped and each
    CIK is committed immediately after ingestion.
    """
    sec_tickers = get_company_tickers()
    ticker_entries = {
        (entry.get("ticker") or "").strip().upper(): entry
        for entry in sec_tickers.values()
        if entry.get("ticker") and entry.get("cik_str") is not None
    }
    if tickers:
        requested = {ticker.upper() for ticker in tickers}
        ticker_entries = {ticker: entry for ticker, entry in ticker_entries.items() if ticker in requested}

    stats = {
        "fetched": 0,
        "stored_submissions": 0,
        "stored_facts": 0,
        "missing": 0,
        "unavailable": 0,
        "errors": 0,
        "skipped": 0,
        "processed_ciks": 0,
    }

    with engine.connect() as conn:
        securities = {
            row["ticker"].upper(): row
            for row in load_companyfacts_targets(conn, tickers, dividend_only)
        }
        entries_by_cik = {}
        for ticker, entry in ticker_entries.items():
            security = securities.get(ticker)
            if security is None:
                stats["missing"] += 1
                continue
            entries_by_cik.setdefault(normalize_cik(entry["cik_str"]), []).append(
                (ticker, entry.get("title") or "", security)
            )

        existing = existing_facts_ciks(conn)
        pending = [cik for cik in entries_by_cik if cik not in existing]
        stats["skipped"] = len(entries_by_cik) - len(pending)
        if max_ciks:
            pending = pending[:max_ciks]

        for cik in pending:
            _ingest_cik(conn, cik, entries_by_cik[cik], stats)
            conn.commit()
            stats["processed_ciks"] += 1
            if stats["processed_ciks"] % 100 == 0:
                print(
                    f"  Progress: {stats['processed_ciks']}/{len(pending)} CIKs, "
                    f"submissions={stats['stored_submissions']}, "
                    f"facts={stats['stored_facts']}, errors={stats['errors']}",
                    flush=True,
                )

    print(
        f"Completed: fetched={stats['fetched']}, submissions={stats['stored_submissions']}, "
        f"companyfacts={stats['stored_facts']}, missing_securities={stats['missing']}, "
        f"unavailable={stats['unavailable']}, errors={stats['errors']}, "
        f"skipped={stats['skipped']}, processed_ciks={stats['processed_ciks']}",
        flush=True,
    )
    return stats["stored_facts"]


def populate_preferred_companyfacts(tickers=None, max_ciks=None):
    """Download SEC history and XBRL company facts for preferred stocks.

    Targets every preferred-stock security recorded in raw.ticker_profile and
    stores its submissions history in raw.sec_submissions and its XBRL payload
    in raw.companyfacts (keyed by the profile's security_id).

    The loader is resumable: each CIK is committed immediately after it is
    fetched, CIKs whose companyfacts already exist are skipped, and
    ``max_ciks`` bounds a single campaign into verifiable batches.
    """
    print("Identifying preferred-stock tickers in raw.ticker_profile...")

    stats = {
        "fetched": 0,
        "stored_submissions": 0,
        "stored_facts": 0,
        "missing": 0,
        "unavailable": 0,
        "errors": 0,
        "skipped": 0,
        "processed_ciks": 0,
    }

    with engine.connect() as conn:
        targets = load_ticker_profile_targets(conn, tickers=tickers)
        entries_by_cik = {}
        for row in targets:
            entries_by_cik.setdefault(row["cik"], []).append(
                (row["ticker"], row["title"], row)
            )
        print(f"  Found {len(targets)} preferred-stock tickers ({len(entries_by_cik)} unique CIKs).")

        existing = existing_facts_ciks(conn)
        pending = [cik for cik in entries_by_cik if cik not in existing]
        stats["skipped"] = len(entries_by_cik) - len(pending)
        print(
            f"  Skipping {stats['skipped']} CIKs already stored; fetching {len(pending)}."
        )
        if max_ciks:
            pending = pending[:max_ciks]
            print(f"  Batch limited to {len(pending)} CIKs.")

        for cik in pending:
            _ingest_cik(conn, cik, entries_by_cik[cik], stats)
            conn.commit()
            stats["processed_ciks"] += 1
            if stats["processed_ciks"] % 50 == 0:
                print(
                    f"  Progress: {stats['processed_ciks']}/{len(pending)} CIKs, "
                    f"submissions={stats['stored_submissions']}, "
                    f"facts={stats['stored_facts']}, errors={stats['errors']}",
                    flush=True,
                )

    print(
        f"Completed: fetched={stats['fetched']}, submissions={stats['stored_submissions']}, "
        f"companyfacts={stats['stored_facts']}, missing_securities={stats['missing']}, "
        f"unavailable={stats['unavailable']}, errors={stats['errors']}, "
        f"skipped={stats['skipped']}, processed_ciks={stats['processed_ciks']}",
        flush=True,
    )
    return stats["stored_facts"]


def _ingest_taxonomy_cik(conn, cik, linked_entries, taxonomy_concepts, stats):
    """Fetch taxonomy-scoped preferred-stock concepts once per CIK.

    The per-issuer payload is stored as a single CIK-keyed row in
    raw.company_taxonomy, shared by every preferred series of the issuer.
    Concepts the issuer never reported (HTTP 404) are skipped and counted, not
    treated as errors.
    """
    ticker, title, _ = linked_entries[0]
    taxonomy_payload = {}
    request_failed = False

    for taxonomy, concepts in taxonomy_concepts.items():
        present = {}
        for concept in concepts:
            try:
                present[concept] = get_companyconcept(cik, taxonomy, concept)
                stats["fetched"] += 1
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    stats["unavailable"] += 1
                    continue
                stats["errors"] += 1
                request_failed = True
                print(f"Error fetching {taxonomy}:{concept} for {ticker} (CIK {cik}): {exc}")
            except Exception as exc:
                stats["errors"] += 1
                request_failed = True
                print(f"Error fetching {taxonomy}:{concept} for {ticker} (CIK {cik}): {exc}")
        if present:
            taxonomy_payload[taxonomy] = present

    stats["processed_ciks"] = stats.get("processed_ciks", 0) + 1
    if request_failed:
        stats["failed_ciks"] = stats.get("failed_ciks", 0) + 1
        return
    if not taxonomy_payload:
        stats["empty_ciks"] = stats.get("empty_ciks", 0) + 1

    try:
        upsert_company_taxonomy(conn, cik, title or ticker, taxonomy_payload)
        stats["stored_taxonomy"] += 1
    except Exception as exc:
        stats["errors"] += 1
        print(f"Error storing taxonomy for {ticker} (CIK {cik}): {exc}")


def resolve_taxonomy_concepts(taxonomies=None):
    """Normalize a ``--taxonomies`` list into the taxonomy->concept map.

    ``None`` returns the default ``PREFERRED_TAXONOMY_CONCEPTS``. Known SEC
    taxonomies with no mapped preferred-stock concepts are accepted when mixed
    with a taxonomy that has concepts; unknown names and zero-concept
    selections are rejected.
    """
    if taxonomies is None:
        return PREFERRED_TAXONOMY_CONCEPTS
    normalized = [taxonomy.strip().lower() for taxonomy in taxonomies if taxonomy.strip()]
    unknown = sorted(set(normalized) - set(PREFERRED_TAXONOMY_CONCEPTS))
    if unknown:
        raise ValueError(f"Unknown taxonomy: {', '.join(unknown)}")
    resolved = {taxonomy: PREFERRED_TAXONOMY_CONCEPTS[taxonomy] for taxonomy in normalized}
    if not any(resolved.values()):
        raise ValueError("At least one taxonomy concept must be selected")
    return resolved


def populate_preferred_taxonomy(tickers=None, taxonomies=None):
    """Download XBRL taxonomy data for preferred stocks in reference.securities.

    Uses the SEC XBRL Data API ``companyconcept`` endpoint to fetch per-concept
    facts (e.g. ``us-gaap``, ``ifrs-full``, ``dei``, or ``srt``) for every
    active preferred stock in reference.securities and stores them in
    raw.company_taxonomy. ``taxonomies`` overrides the default taxonomy->concept
    map (``PREFERRED_TAXONOMY_CONCEPTS``); unknown taxonomies resolve to an
    empty concept list and are simply skipped.
    """
    taxonomies = resolve_taxonomy_concepts(taxonomies)

    print("Identifying preferred-stock tickers in reference.securities...")

    stats = {
        "fetched": 0,
        "stored_taxonomy": 0,
        "missing": 0,
        "unavailable": 0,
        "errors": 0,
        "processed_ciks": 0,
        "failed_ciks": 0,
        "empty_ciks": 0,
    }

    with engine.begin() as conn:
        targets = load_preferred_securities(conn, tickers=tickers)
        entries_by_cik = {}
        for row in targets:
            normalized_cik = normalize_cik(row["cik"])
            entries_by_cik.setdefault(normalized_cik, []).append(
                (row["ticker"], row["title"], row)
            )
        if tickers:
            selected_tickers = {row["ticker"].upper() for row in targets}
            stats["missing"] = len({ticker.upper() for ticker in tickers} - selected_tickers)
        print(
            f"  Found {len(targets)} preferred-stock tickers "
            f"({len(entries_by_cik)} unique CIKs)."
        )
        concepts_per_cik = sum(len(concepts) for concepts in taxonomies.values())
        planned_requests = len(entries_by_cik) * concepts_per_cik
        print(f"  Planned SEC concept requests: {planned_requests}")

        total_ciks = len(entries_by_cik)
        for cik, linked_entries in entries_by_cik.items():
            _ingest_taxonomy_cik(conn, cik, linked_entries, taxonomies, stats)
            if stats["processed_ciks"] % 100 == 0 or stats["processed_ciks"] == total_ciks:
                print(
                    f"  Progress: {stats['processed_ciks']}/{total_ciks} CIKs, "
                    f"fetched={stats['fetched']}, unavailable={stats['unavailable']}, "
                    f"errors={stats['errors']}"
                )

    print(
        f"Completed: fetched={stats['fetched']}, taxonomy={stats['stored_taxonomy']}, "
        f"missing_securities={stats['missing']}, "
        f"unavailable={stats['unavailable']}, errors={stats['errors']}, "
        f"processed_ciks={stats['processed_ciks']}, failed_ciks={stats['failed_ciks']}, "
        f"empty_ciks={stats['empty_ciks']}"
    )
    return stats["stored_taxonomy"] if stats["errors"] == 0 else -stats["errors"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated ticker symbols")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include non-dividend securities (by default only dividend payers are downloaded)",
    )
    parser.add_argument(
        "--preferred",
        action="store_true",
        help="Populate baseline preferred-stock terms from reference.securities",
    )
    parser.add_argument(
        "--preferred-facts",
        action="store_true",
        help="Download SEC history and XBRL company facts for preferred stocks recorded in raw.ticker_profile",
    )
    parser.add_argument(
        "--preferred-taxonomy",
        action="store_true",
        help="Download XBRL company taxonomy facts via the XBRL Data API for preferred stocks in reference.securities",
    )
    parser.add_argument(
        "--taxonomies",
        help="Comma-separated taxonomies to fetch for --preferred-taxonomy "
             "(default: us-gaap,dei; e.g. us-gaap,ifrs-full,dei,srt)",
    )
    parser.add_argument(
        "--max-ciks",
        type=int,
        default=None,
        help="Bound a single --preferred-facts / --all run to this many CIKs "
             "(resume-safe: already-fetched CIKs are skipped on re-run)",
    )
    args = parser.parse_args()
    tickers = [value.strip().upper() for value in args.tickers.split(",") if value.strip()] if args.tickers else None
    dividend_only = not args.all
    try:
        if args.preferred:
            populate_preferred_stocks()
        if args.preferred_facts:
            populate_preferred_companyfacts(tickers=tickers, max_ciks=args.max_ciks)
            return 0
        if args.preferred_taxonomy:
            if args.taxonomies:
                taxonomies = [value.strip() for value in args.taxonomies.split(",") if value.strip()]
            else:
                taxonomies = None
            result = populate_preferred_taxonomy(tickers=tickers, taxonomies=taxonomies)
            return 0 if result >= 0 else 1
        if args.preferred and not tickers:
            return 0
        populate_companyfacts(tickers=tickers, dividend_only=dividend_only, max_ciks=args.max_ciks)
    except Exception as exc:
        print(f"Companyfacts ingestion failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
