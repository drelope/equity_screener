"""
Populate reference tables (exchanges, issuers, securities) with SEC API data.

The raw.company_ticker universe that reference.securities depends on is
populated separately by scripts.populate_raw_tables.

reference.securities keeps one row per SEC-listed instrument: every
raw.company_ticker row (and the matching symbol in the stored submissions
``tickers[]``) names one listed series, and the CIK-level XBRL concept set is
collapsed to a single security_type by
``src.crispdm.sec_client.security_type_for_instrument`` instead of fanning out
one row per concept bucket. Rows left over from previous concept-based runs
are reconciled: childless duplicates for the same (ticker, cik) are removed,
rows still referenced by downstream tables are reported and kept.

Usage:
    python -m scripts.populate_reference_tables [--limit N] [--exchanges] [--issuers] [--securities] [--legacy-sec] [--repopulate]

Options:
    --limit N          Limit to first N securities (for testing)
    --exchanges        Only populate exchanges table
    --issuers          Only populate issuers table
    --securities       Only populate securities table
    --legacy-sec       Repair missing issuer fields from legacy SEC CompanyDBSearch
    --repopulate       Full reseed: reconcile every instrument and delete
                       childless rows whose (ticker, cik) pair is no longer in
                       the SEC company_tickers snapshot
    --reclassify       Ignore the raw.company_classification cache and recompute
                       every classification from the stored companyfacts payloads,
                       refreshing the cache. Use after a change to the
                       classify_companyfacts rules (e.g. the per-share dividend
                       universe rule) so the reference universe and the cache agree.
    (If no options specified, populates all three tables)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.dividend_universe import observed_payer_keys
from src.crispdm.openbb_client import profile as openbb_profile
from src.crispdm.sec_client import (
    classify_companyfacts,
    classify_instrument,
    configured_dividend_lookback,
    get_company_tickers,
    get_companyfacts_concepts,
    get_exchange_list,
    get_issuer_data,
    get_legacy_issuer_data,
    match_security_title,
)
from src.crispdm.stage import stage_exit_code


def get_issuer_info_with_fallback(cik, ticker, title):
    """Prefer SEC issuer metadata and fall back to an OpenBB yahoo source to collect company profile."""
    try:
        issuer_info = get_issuer_data(cik)
        if issuer_info and any(
            issuer_info.get(field) for field in ("issuer_name", "sic", "fiscal_year_end")
        ):
            return issuer_info, "SEC"
    except Exception as exc:
        print(f"  SEC issuer lookup unavailable for {ticker}: {exc}")

    try:
        profile_data = openbb_profile(ticker)
        if profile_data is not None and not profile_data.empty:
            profile = profile_data.iloc[0].to_dict()
            issuer_name = next(
                (
                    profile.get(field)
                    for field in ("name", "company_name", "long_name")
                    if profile.get(field)
                ),
                title,
            )
            sic = next(
                (profile.get(field) for field in ("sic", "sic_code") if profile.get(field)),
                None,
            )
            fiscal_year_end = next(
                (
                    profile.get(field)
                    for field in ("fiscal_year_end", "fiscalYearEnd")
                    if profile.get(field)
                ),
                None,
            )
            return {
                "cik": cik,
                "issuer_name": issuer_name,
                "sic": str(sic) if sic is not None else None,
                "fiscal_year_end": fiscal_year_end,
            }, "OpenBB"
    except Exception as exc:
        print(f"  OpenBB issuer lookup unavailable for {ticker}: {exc}")

    return None, None


def populate_exchanges():
    """Populate reference.exchanges with major US stock exchanges."""
    print("Populating reference.exchanges...")
    exchanges = get_exchange_list()

    with engine.connect() as conn:
        for exchange in exchanges:
            try:
                conn.execute(
                    text("""
                    INSERT INTO reference.exchanges (exchange_code, exchange_name)
                    VALUES (:code, :name)
                    ON CONFLICT (exchange_code) DO NOTHING
                """),
                    {"code": exchange["code"], "name": exchange["name"]},
                )
            except Exception as e:
                print(f"  Error inserting exchange {exchange['code']}: {e}")

        conn.commit()
    print(f"  Populated {len(exchanges)} exchanges.")


def populate_issuers(limit=None):
    """Populate reference.issuers with SEC issuer data."""
    print("Populating reference.issuers...")

    tickers_data = get_company_tickers()
    count = 0
    errors = 0
    issuer_cache = {}

    with engine.connect() as conn:
        for entry in tickers_data.values():
            if limit and count >= limit:
                break

            cik = entry.get("cik_str")
            ticker = entry.get("ticker")
            title = entry.get("title", "").strip()

            try:
                if cik not in issuer_cache:
                    issuer_cache[cik] = get_issuer_info_with_fallback(cik, ticker, title)
                issuer_info, issuer_source = issuer_cache[cik]
                if issuer_info:
                    conn.execute(
                        text("""
                        INSERT INTO reference.issuers (cik, issuer_name, sic, fiscal_year_end)
                        VALUES (:cik, :issuer_name, :sic, :fiscal_year_end)
                        ON CONFLICT (cik) DO UPDATE SET
                            issuer_name = EXCLUDED.issuer_name,
                            sic = EXCLUDED.sic,
                            fiscal_year_end = EXCLUDED.fiscal_year_end
                    """),
                        {
                            "cik": issuer_info["cik"],
                            "issuer_name": issuer_info.get("issuer_name") or title,
                            "sic": issuer_info.get("sic"),
                            "fiscal_year_end": issuer_info.get("fiscal_year_end"),
                        },
                    )
                    count += 1
                    if issuer_source == "OpenBB":
                        print(f"  Used OpenBB issuer profile for {ticker}")
                    if count % 50 == 0:
                        conn.commit()
                        print(f"  Inserted {count} issuers...")
            except Exception as e:
                errors += 1
                print(f"  Error processing {ticker} (CIK {cik}): {e}")
                if errors > 10:
                    print("  Too many errors, stopping issuers population.")
                    break

        conn.commit()

    print(f"  Successfully populated {count} issuers ({errors} errors).")


def populate_missing_issuers_from_legacy_sec(limit=None):
    """Repair missing issuer fields using the optional legacy SEC page."""
    print("Updating missing issuer fields from legacy SEC CompanyDBSearch...")
    repaired = 0
    attempted = 0

    with engine.begin() as conn:
        rows = (
            conn.execute(
                text("""
            SELECT i.issuer_id, i.cik, t.ticker, t.title
            FROM reference.issuers i
            LEFT JOIN raw.company_ticker t ON t.cik = i.cik
            WHERE NULLIF(i.sic, '') IS NULL
               OR i.fiscal_year_end IS NULL
            ORDER BY i.cik, t.ticker
        """)
            )
            .mappings()
            .all()
        )

        seen_ciks = set()
        for row in rows:
            if row["cik"] in seen_ciks:
                continue
            if limit is not None and attempted >= limit:
                break
            seen_ciks.add(row["cik"])
            attempted += 1
            legacy = get_legacy_issuer_data(row["cik"])
            if not legacy:
                continue

            result = conn.execute(
                text("""
                UPDATE reference.issuers
                SET issuer_name = COALESCE(NULLIF(issuer_name, ''), :issuer_name),
                    sic = COALESCE(NULLIF(sic, ''), :sic),
                    fiscal_year_end = COALESCE(fiscal_year_end, :fiscal_year_end)
                WHERE issuer_id = :issuer_id
                  AND (
                      (NULLIF(sic, '') IS NULL AND :sic IS NOT NULL)
                      OR (fiscal_year_end IS NULL AND :fiscal_year_end IS NOT NULL)
                  )
            """),
                {
                    "issuer_id": row["issuer_id"],
                    "issuer_name": legacy.get("issuer_name") or row["title"],
                    "sic": legacy.get("sic"),
                    "fiscal_year_end": legacy.get("fiscal_year_end"),
                },
            )
            repaired += result.rowcount

    print(f"  Repaired {repaired} issuer records from legacy SEC data.")
    return repaired


EXCHANGE_ALIASES = {
    "nasdaq": "NASDAQ",
    "nyse": "NYSE",
    "arca": "ARCA",
    "american": "AMEX",
    "amex": "AMEX",
    "bats": "BATS",
    "pink": "PINK",
    "otc": "PINK",
}


#: SEC_ETL_OFFLINE=1 runs every stage from payloads already stored in the
#: raw schema (companyfacts / submissions / company_ticker) and never opens a
#: data.sec.gov connection. CIKs without a stored payload are marked
#: 'unavailable' instead of being fetched.
def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()


def _normalize_exchange(value):
    """Map a SEC submissions exchange label onto a reference.exchanges code."""
    if not value:
        return None
    tokens = re.sub(r"[^a-z]+", " ", str(value).lower()).split()
    if not tokens:
        return None
    for token in tokens:
        if token in EXCHANGE_ALIASES:
            return EXCHANGE_ALIASES[token]
    for alias in ("nasdaq", "nyse", "american", "bats", "pink"):
        if alias in tokens:
            return EXCHANGE_ALIASES[alias]
    return None


def _load_submissions(conn, ciks):
    """Map CIK -> submissions ticker symbols and their registered exchanges.

    The modern submissions payload (raw.sec_submissions) has no per-instrument
    ``securities`` array; its ``tickers[]``/``exchanges[]`` parallel lists name
    the issuer's listed series and where each trades.
    """
    if not ciks:
        return {}
    rows = (
        conn.execute(
            text("""
            SELECT cik, raw_payload
            FROM raw.sec_submissions
            WHERE cik = ANY(:ciks)
        """),
            {"ciks": sorted(ciks)},
        )
        .mappings()
        .all()
    )
    submissions_by_cik = {}
    for row in rows:
        payload = row["raw_payload"]
        if not isinstance(payload, dict):
            continue
        tickers = payload.get("tickers") or []
        exchanges = payload.get("exchanges") or []
        submissions_by_cik[row["cik"]] = {
            "symbols": {str(symbol).upper() for symbol in tickers if symbol},
            "exchange_by_symbol": {
                str(symbol).upper(): str(exchange)
                for symbol, exchange in zip(tickers, exchanges)
                if symbol and exchange
            },
            "order": [str(symbol).upper() for symbol in tickers if symbol],
        }
    return submissions_by_cik


def _exchange_id_for_symbol(conn, exchange_map, submission, ticker):
    """Pick the SEC-registered exchange for a symbol; NASDAQ as legacy default."""
    code = None
    if submission is not None:
        code = submission.get("exchange_by_symbol", {}).get(ticker.upper())
    normalized = _normalize_exchange(code)
    if normalized:
        return exchange_map.get(normalized)
    return exchange_map.get("NASDAQ")


#: Downstream tables that hold a security_id foreign key. A reference.securities
#: row is only deleted when none of these still reference it, so reseeding can
#: never ghost audit/profile/model lineage.
SECURITY_CHILD_TABLES = (
    "raw.market_data",
    "raw.ticker_profile",
    "raw.dividend_data",
    "raw.sec_documents",
    "preferred.contract_terms",
    "preferred.security_terms",
    "preferred.dividend_snapshot",
    "fundamentals.periodic_financials",
    "model.features",
    "model.scores",
    "model.predictions",
    "model.rankings",
    "audit.source_lineage",
    "audit.data_quality",
)

#: Derived tables that --repopulate recomputes from the raw SEC payloads, so
#: their rows for a dropped phantom security are removed together with it. The
#: history/index tables (raw.market_data, raw.sec_documents) are excluded on
#: purpose: they must be explicitly handled, so a security they reference is
#: still reported and kept instead of silently truncated.
RESEED_CASCADE_TABLES = (
    "raw.ticker_profile",
    "raw.dividend_data",
    "preferred.contract_terms",
    "preferred.security_terms",
    "preferred.dividend_snapshot",
    "fundamentals.periodic_financials",
    "model.features",
    "model.scores",
    "model.predictions",
    "model.rankings",
    "audit.source_lineage",
    "audit.data_quality",
)


def _security_has_children(conn, security_id):
    """True when any downstream table still references ``security_id``."""
    union = " UNION ALL ".join(
        f"SELECT 1 FROM {table} WHERE security_id = :sid" for table in SECURITY_CHILD_TABLES
    )
    return bool(conn.execute(text(f"SELECT EXISTS ({union})"), {"sid": str(security_id)}).scalar())


def _deactivate_referenced_security(conn, security_id):
    """Retain a referenced stale row for history without treating it as active."""
    conn.execute(
        text("""
        UPDATE reference.securities
        SET active = FALSE, updated_at = now()
        WHERE security_id = :sid
    """),
        {"sid": str(security_id)},
    )


def _cascade_reseed_children(conn, security_id):
    """Drop the reproducible rows that reference a security being reseeded."""
    removed = 0
    for table in RESEED_CASCADE_TABLES:
        result = conn.execute(
            text(f"DELETE FROM {table} WHERE security_id = :sid"),
            {"sid": str(security_id)},
        )
        removed += result.rowcount
    return removed


def _reconcile_instrument_rows(conn, ticker, cik, keep_type, dividend, log, repopulate=False):
    """Remove stale reference.securities rows for one (ticker, cik) instrument.

    Prior concept-based runs wrote one row per XBRL bucket; only the row whose
    (security_type, dividend) tuple matches the freshly resolved instrument
    survives here. Rows for the instrument that differ in *either* field are
    stale, so a phantom carrying a different dividend flag is swept too (e.g. a
    placeholder written while the issuer was unclassified). With ``repopulate``
    the reproducible derived rows are rebuilt, so their phantom parent is
    cleared. Stale rows still referenced by history or audit tables are retained
    but deactivated.
    """
    stale = (
        conn.execute(
            text("""
            SELECT security_id, security_type, dividend
            FROM reference.securities
            WHERE ticker = :ticker AND cik = :cik
              AND (security_type, dividend) IS DISTINCT FROM (:keep_type, :keep_dividend)
            ORDER BY security_id
        """),
            {
                "ticker": ticker,
                "cik": cik,
                "keep_type": keep_type,
                "keep_dividend": dividend,
            },
        )
        .mappings()
        .all()
    )
    for row in stale:
        if repopulate:
            log["cascaded"] += _cascade_reseed_children(conn, row["security_id"])
        if _security_has_children(conn, row["security_id"]):
            _deactivate_referenced_security(conn, row["security_id"])
            log["deactivated_with_children"].append((ticker, row["security_type"]))
            continue
        conn.execute(
            text("DELETE FROM reference.securities WHERE security_id = :sid"),
            {"sid": str(row["security_id"])},
        )
        log["deleted"] += 1


def _sweep_orphan_securities(conn, log, repopulate=False):
    """Delete childless rows whose (ticker, cik) is no longer in the SEC snapshot."""
    orphans = (
        conn.execute(
            text("""
            SELECT s.security_id, s.ticker, s.cik
            FROM reference.securities s
            WHERE NOT EXISTS (
                SELECT 1
                FROM raw.company_ticker t
                WHERE t.ticker = s.ticker AND t.cik = s.cik
            )
            ORDER BY s.ticker, s.cik
        """)
        )
        .mappings()
        .all()
    )
    for row in orphans:
        if repopulate:
            log["cascaded"] += _cascade_reseed_children(conn, row["security_id"])
        if _security_has_children(conn, row["security_id"]):
            _deactivate_referenced_security(conn, row["security_id"])
            log["deactivated_with_children"].append((row["ticker"], "orphan"))
            continue
        conn.execute(
            text("DELETE FROM reference.securities WHERE security_id = :sid"),
            {"sid": str(row["security_id"])},
        )
        log["deleted"] += 1
    return len(orphans)


#: A securities run that fails on more than this many securities stops, and the stage fails.
MAX_SECURITY_ERRORS = 10


def _relabel_legacy_holder(conn, row_id, ticker, cik, security_type, dividend):
    """Correct a legacy row that already holds the id this key hashes to.

    security_id is a hash of (ticker, cik, security_type, dividend). A row whose flag was
    flipped in place keeps the id of its *old* key, so when the instrument resolves back to
    that key the insert collides on securities_security_id_key. The id says what the row
    is, so relabel it to match rather than collide. security_id is untouched, so no child
    row moves. A row already holding the target key is left to the upsert.
    """
    conn.execute(
        text("""
        UPDATE reference.securities s
        SET ticker = :ticker, cik = :cik, security_type = :type, dividend = :dividend,
            updated_at = now()
        WHERE s.security_id = :id
          AND (s.ticker, s.cik, s.security_type, s.dividend)
              IS DISTINCT FROM (:ticker, :cik, :type, :dividend)
          AND NOT EXISTS (
              SELECT 1 FROM reference.securities o
              WHERE (o.ticker, o.cik, o.security_type, o.dividend)
                    = (:ticker, :cik, :type, :dividend)
                AND o.security_id <> :id)
    """),
        {
            "id": row_id,
            "ticker": ticker,
            "cik": cik,
            "type": security_type,
            "dividend": dividend,
        },
    )


def _upsert_classification_cache(conn, cik, ticker, company_name, classification):
    """Refresh one raw.company_classification row from a reclassified payload.

    Keeps the same content_hash contract as the other cache writers: hashed on
    ``dividend_facts`` only, so a reclassification that changes the boolean but
    not the evidence leaves the hash untouched and the row repopulated.
    """
    conn.execute(
        text("""
        INSERT INTO raw.company_classification
            (cik, ticker, company_name, security_types, security_titles,
             security_facts, dividend_facts, dividend, dividend_last_paid,
             status, content_hash, retrieved_at)
        VALUES (:cik, :ticker, :company_name, CAST(:security_types AS jsonb),
                CAST(:security_titles AS jsonb), CAST(:security_facts AS jsonb),
                CAST(:dividend_facts AS jsonb),
                :dividend, :dividend_last_paid, :status, :content_hash, now())
        ON CONFLICT (cik) DO UPDATE SET
            ticker = EXCLUDED.ticker,
            company_name = EXCLUDED.company_name,
            security_types = EXCLUDED.security_types,
            security_titles = EXCLUDED.security_titles,
            security_facts = EXCLUDED.security_facts,
            dividend_facts = EXCLUDED.dividend_facts,
            dividend = EXCLUDED.dividend,
            dividend_last_paid = EXCLUDED.dividend_last_paid,
            status = EXCLUDED.status,
            content_hash = EXCLUDED.content_hash,
            retrieved_at = now()
    """),
        {
            "cik": cik,
            "ticker": ticker,
            "company_name": company_name,
            "security_types": json.dumps(classification["security_types"]),
            "security_titles": json.dumps(classification.get("security_titles", [])),
            "security_facts": json.dumps(classification["security_facts"]),
            "dividend_facts": json.dumps(classification["dividend_facts"]),
            "dividend": classification["dividend"],
            "dividend_last_paid": classification.get("dividend_last_paid"),
            "status": classification["status"],
            "content_hash": hashlib.sha256(
                json.dumps(classification["dividend_facts"], sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
    )


def populate_securities(limit=None, repopulate=False, reclassify=False):
    """Build audited security rows from raw tickers and SEC Company Facts.

    One row per SEC-listed instrument: ``raw.company_ticker`` already enumerates
    the issuer's registered series (each symbol is one class), so the CIK-level
    concept-bucket set from ``classify_companyfacts`` is collapsed to a single
    security_type instead of being fanned out into a row per bucket.
    """
    print("Populating reference.securities...")

    count = 0
    errors = 0

    with engine.connect() as conn:
        # Pre-fetch exchange mapping
        exchanges = conn.execute(
            text("SELECT exchange_id, exchange_code FROM reference.exchanges")
        ).mappings()
        exchange_map = {e["exchange_code"]: e["exchange_id"] for e in exchanges}

        limit_sql = " LIMIT :limit" if limit else ""
        raw_tickers = list(
            conn.execute(
                text(f"""
            SELECT ticker, cik, title
            FROM raw.company_ticker
            ORDER BY ticker
            {limit_sql}
        """),
                {"limit": limit} if limit else {},
            ).mappings()
        )
        batch_ciks = {row["cik"] for row in raw_tickers if row["cik"] is not None}
        observed_payers = observed_payer_keys(conn)
        cik_tickers = {sec["cik"]: sec["ticker"] for sec in raw_tickers if sec["cik"]}
        cik_titles = {sec["cik"]: sec["title"] for sec in raw_tickers if sec["cik"]}

        issuer_id_by_cik = {}
        existing_names_by_key = {}
        if batch_ciks:
            issuer_rows = conn.execute(
                text("""
                SELECT cik, issuer_id
                FROM reference.issuers
                WHERE cik = ANY(:ciks)
            """),
                {"ciks": sorted(batch_ciks)},
            ).mappings()
            issuer_id_by_cik = {row["cik"]: row["issuer_id"] for row in issuer_rows}

            existing_rows = conn.execute(
                text("""
                SELECT cik, ticker, security_type, dividend, security_name
                FROM reference.securities
                WHERE cik = ANY(:ciks)
                ORDER BY updated_at DESC NULLS LAST
            """),
                {"ciks": sorted(batch_ciks)},
            ).mappings()
            for row in existing_rows:
                key = (row["cik"], row["ticker"], row["security_type"], row["dividend"])
                existing_names_by_key.setdefault(key, row["security_name"])

        facts_by_cik = {}
        cache_rows = conn.execute(
            text("""
            SELECT cik, security_types, security_titles, security_facts,
                   dividend_facts, dividend, dividend_last_paid, status
            FROM raw.company_classification
            WHERE content_hash IS NOT NULL
        """)
        ).mappings()
        for row in cache_rows:
            facts_by_cik[row["cik"]] = {
                "security_types": row["security_types"],
                "security_titles": row["security_titles"],
                "dividend": row["dividend"],
                "security_facts": row["security_facts"],
                "dividend_facts": row["dividend_facts"],
                "dividend_last_paid": row["dividend_last_paid"],
                "status": row["status"],
            }

        # Warm the classification map from payloads already persisted by stage
        # 0/3 (raw.companyfacts) instead of re-downloading the issuer JSON from
        # SEC. Only CIKs without a stored payload fall through to the API. When
        # a batch limit is given, restrict the warm scan to CIKs in the batch so
        # a limited run never touches the full 1.4 GB payload set.
        #
        # --reclassify empties the cache set so every batch CIK with a stored
        # payload is classified again under the current rules and written back
        # to raw.company_classification.
        cached_ciks = set() if reclassify else set(facts_by_cik)
        stored_sql = text("""
            SELECT cik, raw_payload
            FROM raw.companyfacts
            WHERE cik IS NOT NULL AND content_hash IS NOT NULL
              AND cik = ANY(:ciks)
        """)
        # Only CIKs missing from the classification cache need their payload
        # parsed. Selecting every CIK buffered the whole payload set client-side
        # and was OOM-killed at ~14.5 GB on the 2026-10-05 nightly run, so the
        # rows are also streamed instead of materialised.
        stored_facts = conn.execute(
            stored_sql.execution_options(stream_results=True),
            {"ciks": sorted(batch_ciks - cached_ciks)},
        ).mappings()
        for row in stored_facts:
            if row["cik"] not in cached_ciks:
                try:
                    classification = classify_companyfacts(
                        row["raw_payload"], lookback_days=configured_dividend_lookback()
                    )
                    facts_by_cik[row["cik"]] = classification
                    if reclassify and cik_tickers.get(row["cik"]):
                        _upsert_classification_cache(
                            conn,
                            row["cik"],
                            cik_tickers[row["cik"]],
                            cik_titles.get(row["cik"]),
                            classification,
                        )
                except Exception:
                    continue

        # SEC live-fetch fallback for CIKs without a stored companyfacts payload.
        # In offline mode (SEC_ETL_OFFLINE=1) no data.sec.gov request is opened:
        # issuers without stored facts are marked 'unavailable' instead of being
        # fetched, so air-gapped reseeds still converge.
        missing_ciks = sorted({sec["cik"] for sec in raw_tickers if sec["cik"] not in facts_by_cik})
        if OFFLINE_ON:
            for cik in missing_ciks:
                facts_by_cik[cik] = {
                    "security_types": ["other"],
                    "dividend": False,
                    "security_titles": [],
                    "security_facts": [{"status": "unavailable", "error": "offline"}],
                    "dividend_facts": [],
                    "status": "unavailable",
                }
            if missing_ciks:
                print(
                    f"  OFFLINE: marked {len(missing_ciks)} issuers without stored facts as unavailable."
                )
        else:
            for cik in missing_ciks:
                try:
                    facts_by_cik[cik] = classify_companyfacts(
                        get_companyfacts_concepts(cik), lookback_days=configured_dividend_lookback()
                    )
                except Exception as exc:
                    facts_by_cik[cik] = {
                        "security_types": ["other"],
                        "dividend": False,
                        "security_titles": [],
                        "security_facts": [{"status": "unavailable", "error": type(exc).__name__}],
                        "dividend_facts": [],
                        "status": "unavailable",
                    }
                    print(f"  SEC Company Facts unavailable for CIK {cik}: {exc}")

        submissions_by_cik = _load_submissions(conn, set(batch_ciks) | set(facts_by_cik))

        # per-instrument dei cover-page titles (raw.sec_instrument_titles),
        # sourced from filing XBRL instances, paired to each trading symbol.
        # XBRL TradingSymbols typically drop separators ("KRGPI" for "KRG-PI"),
        # so both the exact symbol and its normalized form are indexed.
        titles_by_cik = {}
        titles_list_by_cik = {}
        for title_row in conn.execute(
            text("""
            SELECT cik, ticker, title
            FROM raw.sec_instrument_titles
        """)
        ).mappings():
            symbol = str(title_row["ticker"]).upper()
            titles_by_cik.setdefault(title_row["cik"], {}).setdefault(symbol, title_row["title"])
            titles_by_cik[title_row["cik"]].setdefault(
                re.sub(r"[\-.]", "", symbol), title_row["title"]
            )
            titles_list_by_cik.setdefault(title_row["cik"], {}).setdefault(title_row["title"], None)
        titles_list_by_cik = {cik: list(titles) for cik, titles in titles_list_by_cik.items()}
        reconcile_log = {"deleted": 0, "cascaded": 0, "deactivated_with_children": []}

        for sec in raw_tickers:
            # One security's failure must not poison the rest: a failed statement aborts the
            # whole transaction, so without a savepoint every later security fails with
            # "current transaction is aborted" and the stage stops after 11 errors.
            savepoint = conn.begin_nested()
            try:
                cik = sec["cik"]
                classification = facts_by_cik[cik]

                issuer_id = issuer_id_by_cik.get(cik)

                ticker_key = sec["ticker"].upper()
                exact_title = (titles_by_cik.get(cik) or {}).get(ticker_key) or (
                    titles_by_cik.get(cik) or {}
                ).get(re.sub(r"[\-.]", "", ticker_key))
                cik_titles = titles_list_by_cik.get(cik) or []
                instrument = classify_instrument(
                    sec["ticker"],
                    classification,
                    dei_titles=(
                        [exact_title]
                        if exact_title
                        else cik_titles or classification.get("security_titles", [])
                    ),
                    submissions=submissions_by_cik.get(cik),
                    issuer_name=sec["title"],
                )
                security_type = instrument.security_type
                dividend = classification["dividend"] or (cik, sec["ticker"]) in observed_payers
                row_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"dividend-equity:{sec['ticker'].upper()}:{cik}:{security_type}:{dividend}",
                )
                title_match = match_security_title(
                    cik_titles or classification.get("security_titles", []),
                    security_type,
                )
                if exact_title:
                    security_name = exact_title
                    title_source = "sec_instrument_title"
                elif instrument.matched_title:
                    security_name = instrument.matched_title
                    title_source = "sec_companyfacts_title"
                elif title_match:
                    security_name = title_match
                    title_source = "unique_sec_title"
                else:
                    existing_name = existing_names_by_key.get(
                        (cik, sec["ticker"], security_type, dividend)
                    )
                    security_name = existing_name or sec["title"]
                    title_source = (
                        "retained_existing_unverified"
                        if existing_name
                        else "issuer_fallback_unresolved"
                    )
                exchange_id = _exchange_id_for_symbol(
                    conn,
                    exchange_map,
                    submissions_by_cik.get(cik),
                    sec["ticker"],
                )
                _relabel_legacy_holder(conn, row_id, sec["ticker"], cik, security_type, dividend)
                conn.execute(
                    text("""
                    INSERT INTO reference.securities
                    (ticker, cik, security_id, issuer_id, security_name,
                     security_type, dividend, dividend_last_paid, sec_data_status,
                     exchange_id, currency, active,
                     classify_source, classify_confidence, classification_evidence)
                    VALUES (:ticker, :cik, :id, :issuer_id, :security_name,
                        :type, :dividend, :dividend_last_paid, :status, :exchange_id,
                            :currency, :active,
                            :classify_source, :classify_confidence, CAST(:classify_evidence AS jsonb))
                    ON CONFLICT (cik, ticker, security_type, dividend) DO UPDATE SET
                        issuer_id = EXCLUDED.issuer_id,
                        security_name = EXCLUDED.security_name,
                        dividend_last_paid = EXCLUDED.dividend_last_paid,
                        sec_data_status = EXCLUDED.sec_data_status,
                        exchange_id = EXCLUDED.exchange_id,
                        currency = EXCLUDED.currency,
                        active = EXCLUDED.active,
                        classify_source = EXCLUDED.classify_source,
                        classify_confidence = EXCLUDED.classify_confidence,
                        classification_evidence = EXCLUDED.classification_evidence,
                        updated_at = now()
                """),
                    {
                        "id": row_id,
                        "cik": cik,
                        "issuer_id": issuer_id,
                        "ticker": sec["ticker"],
                        "security_name": security_name,
                        "type": security_type,
                        "dividend": dividend,
                        "dividend_last_paid": classification.get("dividend_last_paid"),
                        "status": classification["status"],
                        "exchange_id": exchange_id,
                        "currency": "USD",
                        "active": True,
                        "classify_source": instrument.source,
                        "classify_confidence": instrument.confidence,
                        "classify_evidence": json.dumps(
                            {
                                "source": instrument.source,
                                "confidence": instrument.confidence,
                                "matched_title": instrument.matched_title,
                                "security_name_source": title_source,
                                "dividend_last_paid": classification.get("dividend_last_paid"),
                                "dividend_lookback_start": classification.get(
                                    "dividend_lookback_start"
                                ),
                                "submissions": instrument.submissions,
                                "evidence": instrument.evidence,
                                "conflicts": instrument.conflicts,
                            },
                            default=str,
                        ),
                    },
                )
                _reconcile_instrument_rows(
                    conn,
                    sec["ticker"],
                    cik,
                    security_type,
                    dividend,
                    reconcile_log,
                    repopulate=repopulate,
                )
                savepoint.commit()
                count += 1
                if count % 100 == 0:
                    conn.commit()
                    print(f"  Inserted {count} securities...")

            except Exception as e:
                if savepoint.is_active:
                    savepoint.rollback()
                errors += 1
                print(f"  Error processing {sec.get('ticker')}: {e}")
                if errors > MAX_SECURITY_ERRORS:
                    print("  Too many errors, stopping securities population.")
                    break

        if repopulate:
            orphans = _sweep_orphan_securities(conn, reconcile_log, repopulate=True)
            print(
                f"  Swept {orphans} orphan security rows (deleted {reconcile_log['deleted']} childless so far)."
            )
        conn.commit()

    print(f"  Successfully populated {count} securities ({errors} errors).")
    securities_result = (count + errors, count, errors)
    print(
        f"  Reconcile: deleted {reconcile_log['deleted']} stale rows, "
        f"cascaded {reconcile_log['cascaded']} derived child rows; "
        f"deactivated {len(reconcile_log['deactivated_with_children'])} stale rows still referenced "
        f"downstream: {reconcile_log['deactivated_with_children'][:10]}..."
    )

    validate_securities_reference_fk(check_active_identity_duplicates=limit is None)
    return securities_result


def validate_securities_reference_fk(*, check_active_identity_duplicates=True):
    """Enforce referential integrity after the reference stage finishes.

    ``populate_raw_tables`` (re)creates fk_securities_company_ticker as NOT
    VALID so bulk upserts never lock the parent table; referencing nothing
    validates the constraint. Data that violates it (orphan (ticker, cik)
    pairs) is a pipeline defect, so validation failures surface loudly.
    """
    with engine.begin() as conn:
        if check_active_identity_duplicates:
            duplicate = (
                conn.execute(
                    text("""
                SELECT cik, ticker, COUNT(*) AS active_rows
                FROM reference.securities
                WHERE active = TRUE
                GROUP BY cik, ticker
                HAVING COUNT(*) > 1
                LIMIT 1
            """)
                )
                .mappings()
                .first()
            )
            if duplicate:
                raise RuntimeError(
                    "Multiple active reference.securities rows for "
                    f"(cik={duplicate['cik']}, ticker={duplicate['ticker']})"
                )
        conn.execute(
            text(
                "ALTER TABLE reference.securities VALIDATE CONSTRAINT fk_securities_company_ticker"
            )
        )
    print("  Validated fk_securities_company_ticker.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to first N records (for testing)"
    )
    parser.add_argument("--exchanges", action="store_true", help="Only populate exchanges")
    parser.add_argument("--issuers", action="store_true", help="Only populate issuers")
    parser.add_argument("--securities", action="store_true", help="Only populate securities")
    parser.add_argument(
        "--legacy-sec",
        action="store_true",
        help="Repair missing issuer fields using legacy SEC CompanyDBSearch",
    )
    parser.add_argument(
        "--repopulate",
        action="store_true",
        help="Full reseed: reconcile every instrument and delete "
        "childless rows no longer in the SEC snapshot",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Recompute raw.company_classification from the stored companyfacts "
        "payloads instead of trusting the cache, and refresh the cache",
    )

    args = parser.parse_args()

    # If no specific tables chosen, populate all
    populate_all = not any([args.exchanges, args.issuers, args.securities, args.legacy_sec])

    try:
        if args.exchanges or populate_all:
            populate_exchanges()

        if args.issuers or populate_all:
            populate_issuers(args.limit)

        if args.legacy_sec:
            populate_missing_issuers_from_legacy_sec(args.limit)

        if args.securities or populate_all:
            attempted, written, errors = populate_securities(
                args.limit, repopulate=args.repopulate, reclassify=args.reclassify
            )
            # A run that stops early leaves a partially rebuilt universe, and later stages
            # would read it as complete. The 2026-10-07 nightly stopped at "O" and still
            # reported success because it had written 6,960 rows.
            if errors > MAX_SECURITY_ERRORS:
                print(
                    f"✗ populate_reference_tables (securities) stopped after {errors} errors "
                    f"with {written} of {attempted} processed; the universe is partially rebuilt.",
                    file=sys.stderr,
                )
                return 1
            code = stage_exit_code(
                "populate_reference_tables (securities)", attempted, written, errors=errors
            )
            if code:
                return code

        print("\n✓ Reference tables populated successfully!")
        return 0

    except Exception as e:
        print(f"\n✗ Error populating reference tables: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
