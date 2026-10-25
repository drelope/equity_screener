"""
Populate raw schema tables with SEC API data.

Currently populates raw.company_ticker with the SEC company_tickers.json
snapshot, identifies which tickers issue a dividend, and writes a Ticker
Profile Summary for each dividend payer into raw.ticker_profile.

Dividend payers are identified from SEC Company Facts (the same XBRL
classification used by scripts.populate_reference_tables). The same SEC
Company Facts payload is then mined for preferred-stock coupon_rate and
liquidation_preference XBRL tags (see
src.crispdm.sec_client.extract_preferred_terms_from_companyfacts). Those facts
are issuer-level (no series dimension, and par value is used as a fallback),
so they are stored only as evidence under raw_payload->sec_xbrl with
sec_xbrl_scope = 'issuer_level_unallocated'. The per-series columns come from
the security-title parse in scripts.populate_dividend_data.fetch_ticker_profile,
which also supplies the OpenBB/yfinance profile. Every write goes through
src.crispdm.ticker_profile_store (append-only history + owned-column merge).
A minimal reference.securities row is created for each payer
so the raw.ticker_profile foreign key has a target; scripts.populate_reference_tables
reconciles those rows with full issuer and classification data on its next run.

Usage:
    python -m scripts.populate_raw_tables [--limit N] [--skip-profiles]

Options:
    --limit N          Limit to first N tickers (for testing)
    --skip-profiles    Only populate raw.company_ticker; do not fetch ticker profiles
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from scripts.populate_companyfacts import (
    stored_facts_retrieved_at,
    upsert_companyfacts,
)
from scripts.populate_dividend_data import fetch_ticker_profile
from src.crispdm.db import engine
from src.crispdm.dividend_universe import observed_payer_keys
from src.crispdm.sec_client import (
    build_companyfacts_concept_groups,
    classify_companyfacts,
    configured_dividend_lookback,
    extract_preferred_terms_from_companyfacts,
    get_company_tickers,
    get_companyfacts,
    match_security_title,
    security_type_for_instrument,
)
from src.crispdm.stage import stage_exit_code
from src.crispdm.ticker_profile_store import (
    NAME_PARSE_COLUMNS,
    OPENBB_COLUMNS,
    SEC_XBRL_SCOPE,
    envelope_payload,
    upsert_ticker_profile,
)


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()

TICKER_CIK_CONFLICT = "TICKER_CIK_CONFLICT"

#: audit.quarantined_values.ticker is VARCHAR(16); the full ticker is the row key.
REGISTRY_TICKER_WIDTH = 16


class TickerRefresh(NamedTuple):
    """Outcome of one raw.company_ticker refresh.

    ``seen`` is the snapshot entries the run tried to apply, ``ingested`` those it
    wrote, and ``conflicts`` the entries it deliberately left alone.
    """

    seen: int
    ingested: int
    conflicts: list


def _referenced_ticker_owners(conn):
    """Map ticker -> the stored row that a reference.securities row still points at.

    Only these rows are protected by fk_securities_company_ticker, so only these can
    make an upsert that changes the CIK fail. A row nothing references is free to
    be refreshed, and stays on the existing path.
    """
    rows = (
        conn.execute(
            text("""
            SELECT c.ticker, c.cik, c.title, count(s.security_id) AS securities
            FROM raw.company_ticker c
            JOIN reference.securities s ON s.ticker = c.ticker AND s.cik = c.cik
            GROUP BY c.ticker, c.cik, c.title
        """)
        )
        .mappings()
        .all()
    )
    return {row["ticker"]: row for row in rows}


def _normalise_entry(entry):
    """Return (ticker, zero-padded cik, title) for a snapshot entry, or None if unusable."""
    ticker = (entry.get("ticker") or "").strip().upper()
    if not ticker or entry.get("cik_str") is None:
        return None
    return ticker, str(int(entry["cik_str"])).zfill(10), (entry.get("title") or "").strip()


def _conflict_record(owners, ticker, cik, title):
    """The TICKER_CIK_CONFLICT for one normalised entry, or None if it does not conflict."""
    owner = owners.get(ticker)
    if owner is None or owner["cik"] == cik:
        return None
    return {
        "conflict_type": TICKER_CIK_CONFLICT,
        "ticker": ticker,
        "incoming_cik": cik,
        "incoming_issuer": title,
        "existing_cik": owner["cik"],
        "existing_issuer": owner["title"],
        "referencing_securities": int(owner["securities"]),
        "action": "SKIPPED",
        "resolution": "MANUAL_REVIEW_REQUIRED",
    }


def _refresh_company_tickers(conn, entries):
    """Apply the raw.company_ticker snapshot: FK guard + per-ticker upsert.

    A ticker that the snapshot now assigns to a different CIK than the one a
    security still references is skipped and reported, never reassigned. Containment
    only: this does not decide which issuer owns the ticker, and it does not touch
    the existing row. Every other failure still raises.
    """
    # The legacy UNIQUE(cik) constraint (company_ticker_cik_key) and the old
    # securities_cik_fkey no longer exist in schema.sql or in the live schema,
    # and nothing re-adds them; dropping them nightly was a no-op statement
    # still charged ACCESS EXCLUSIVE -- measured at ~43 min of lock wait per
    # run behind an overnight reader. The guards that remain are the unique
    # index and the composite FK below.
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ux_company_ticker_ticker_cik ON raw.company_ticker(ticker, cik)"
        )
    )
    # Add only when absent. Dropping and re-adding always yields NOT VALID, so every
    # nightly undid V0046's validation and put the live schema back out of step with
    # the repository.
    conn.execute(
        text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'reference.securities'::regclass
                   AND conname = 'fk_securities_company_ticker'
            ) THEN
                ALTER TABLE reference.securities
                ADD CONSTRAINT fk_securities_company_ticker
                FOREIGN KEY (ticker, cik)
                REFERENCES raw.company_ticker(ticker, cik)
                NOT VALID;
            END IF;
        END $$;
    """)
    )

    owners = _referenced_ticker_owners(conn)
    seen = ingested = 0
    conflicts = []
    conflicted = set()

    for entry in entries:
        normalised = _normalise_entry(entry)
        if normalised is None:
            continue
        ticker, cik, title = normalised
        seen += 1

        conflict = _conflict_record(owners, ticker, cik, title)
        if conflict is not None:
            if (ticker, cik) not in conflicted:
                conflicted.add((ticker, cik))
                conflicts.append(conflict)
            continue

        conn.execute(
            text("""
            INSERT INTO raw.company_ticker
                (ticker, cik, title, raw_payload, retrieved_at)
            VALUES (:ticker, :cik, :title, CAST(:raw_payload AS jsonb), now())
            ON CONFLICT (ticker) DO UPDATE SET
                cik = EXCLUDED.cik,
                title = EXCLUDED.title,
                raw_payload = EXCLUDED.raw_payload,
                retrieved_at = EXCLUDED.retrieved_at
        """),
            {
                "ticker": ticker,
                "cik": cik,
                "title": title,
                "raw_payload": json.dumps(entry),
            },
        )
        ingested += 1

    return TickerRefresh(seen=seen, ingested=ingested, conflicts=conflicts)


def record_ticker_conflicts(conn, conflicts, *, sweep):
    """Keep the quarantine registry in step with the conflicts this run skipped.

    The stage exits 0 on a conflict, so the registry is what lets the morning check
    see one without reading the journal. An open row is written once and left alone
    on later nights; a row an operator already resolved is reopened if the conflict
    returns. ``sweep`` resolves open rows the SEC file no longer reports, and is only
    valid for a full, online snapshot: a ``--limit`` run or the offline re-read sees
    a subset and would wrongly close the rest.

    Runs in a savepoint and never raises: a registry problem must not roll back the
    ticker upserts it is reporting on.
    """
    try:
        with conn.begin_nested():
            for conflict in conflicts:
                conn.execute(
                    text("""
                    INSERT INTO audit.quarantined_values
                        (table_schema, table_name, column_name, row_key, cik, ticker,
                         observed_value, reason, rule)
                    VALUES ('raw', 'company_ticker', 'cik', :ticker, :existing_cik, :short,
                            :incoming_cik, :reason, :rule)
                    ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value)
                    DO UPDATE SET resolved_at = NULL, resolution_note = NULL,
                                  detected_at = now(), reason = EXCLUDED.reason
                    WHERE audit.quarantined_values.resolved_at IS NOT NULL
                """),
                    {
                        "ticker": conflict["ticker"],
                        "short": conflict["ticker"][:REGISTRY_TICKER_WIDTH],
                        "existing_cik": conflict["existing_cik"],
                        "incoming_cik": conflict["incoming_cik"],
                        "reason": (
                            f"SEC now lists {conflict['ticker']} under "
                            f"{conflict['incoming_issuer']} (CIK {conflict['incoming_cik']}) "
                            f"while {conflict['referencing_securities']} security row(s) still "
                            f"reference {conflict['existing_issuer']} "
                            f"(CIK {conflict['existing_cik']}); mapping left unchanged"
                        ),
                        "rule": TICKER_CIK_CONFLICT,
                    },
                )
            if sweep:
                still_open = [f"{c['ticker']}|{c['incoming_cik']}" for c in conflicts]
                conn.execute(
                    text("""
                    UPDATE audit.quarantined_values
                    SET resolved_at = now(),
                        resolution_note = 'no longer reported by the SEC ticker file'
                    WHERE rule = :rule AND table_schema = 'raw' AND resolved_at IS NULL
                      AND (row_key || '|' || observed_value) <> ALL(CAST(:still_open AS text[]))
                """),
                    {"rule": TICKER_CIK_CONFLICT, "still_open": still_open},
                )
    except SQLAlchemyError as exc:
        print(f"[populate_raw_tables] could not record ticker conflicts: {exc}", file=sys.stderr)


def report_ticker_conflicts(conflicts):
    """Print the conflicts as one machine-readable line each, then a plain summary.

    The stage still exits 0, and run_full_etl has no status between ok and failed, so
    this output is the only place the conflict is visible. It goes to stderr so a
    journal reader filtering for warnings finds it.
    """
    if not conflicts:
        return
    for conflict in conflicts:
        print(f"[ticker_cik_conflict] {json.dumps(conflict, sort_keys=True)}", file=sys.stderr)
    print(
        f"WARNING: {len(conflicts)} ticker(s) skipped because a security still references "
        "them under a different CIK. No existing ticker mapping was modified.",
        file=sys.stderr,
    )
    for conflict in conflicts:
        print(
            f"  {conflict['ticker']}: incoming {conflict['incoming_issuer']} "
            f"(CIK {conflict['incoming_cik']}) vs existing {conflict['existing_issuer']} "
            f"(CIK {conflict['existing_cik']}); SKIPPED, manual entity-resolution review "
            "required",
            file=sys.stderr,
        )


def populate_company_tickers(limit=None):
    """Persist the SEC company_tickers.json response in raw form.

    In offline mode (SEC_ETL_OFFLINE=1) the snapshot already materialized in
    raw.company_ticker is re-normalized instead of re-downloading
    company_tickers.json, so the stage is idempotent without network access.
    """
    print("Populating raw.company_ticker...")
    if OFFLINE_ON:
        print("  OFFLINE: re-normalizing stored raw.company_ticker rows (no SEC fetch).")
        with engine.begin() as conn:
            rows = (
                conn.execute(
                    text("SELECT ticker, cik, title FROM raw.company_ticker ORDER BY ticker")
                )
                .mappings()
                .all()
            )
            entries = [
                {"ticker": r["ticker"], "cik_str": r["cik"], "title": r["title"]} for r in rows
            ]
            if limit:
                entries = entries[:limit]
            result = _refresh_company_tickers(conn, entries)
        print(f"  Populated {result.ingested} raw company ticker records (offline).")
        return result

    tickers_data = get_company_tickers()
    entries = list(tickers_data.values())
    if limit:
        entries = entries[:limit]

    with engine.begin() as conn:
        result = _refresh_company_tickers(conn, entries)
        record_ticker_conflicts(conn, result.conflicts, sweep=not limit)

    print(f"  Populated {result.ingested} raw company ticker records.")
    return result


def _load_raw_tickers(conn, limit=None):
    """Load ticker/cik/title rows from raw.company_ticker."""
    limit_sql = " LIMIT :limit" if limit else ""
    params = {"limit": limit} if limit else {}
    return (
        conn.execute(
            text(f"""
        SELECT ticker, cik, title
        FROM raw.company_ticker
        ORDER BY ticker
        {limit_sql}
    """),
            params,
        )
        .mappings()
        .all()
    )


def _persist_classification_cache(conn, entries):
    """Persist the compact per-CIK classification cache computed in stage 0.

    Later stages (populate_reference_tables, populate_companyfacts) read this
    cache instead of re-downloading the full SEC companyfacts payload per CIK,
    avoiding the duplicate loads that previously made the ETL slow and the
    storage inefficient.
    """
    for cik, ticker, title, classification in entries:
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
                "company_name": title,
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


def _stored_companyfacts(conn, cik):
    """Read one issuer's companyfacts payload from the raw cache.

    ``_identify_dividend_payers`` persists every payload as it is fetched, so
    later phases (preferred-term extraction, security titles) re-read only the
    issuers they need instead of retaining all ~10k full companyfacts JSON
    documents in memory (that path OOM-killed the stage on this host).
    """
    return conn.execute(
        text(
            "SELECT raw_payload FROM raw.companyfacts WHERE cik = :cik AND content_hash IS NOT NULL"
        ),
        {"cik": cik},
    ).scalar()


# A CIK SEC has no companyfacts for, or whose payload cannot be read. Classified
# as a non-payer rather than an error, so one missing issuer cannot fail a scan.
# How stale a stored companyfacts payload may be and still be reused by this
# scan instead of re-downloaded. Matches the nightly's --companyfacts-refresh-after-days
# default so the two stages agree on when a payload is due; a nightly then fetches
# each CIK once, not twice.
DEFAULT_REUSE_MAX_AGE_DAYS = 5

_UNAVAILABLE = {
    "security_types": ["other"],
    "dividend": False,
    "security_titles": [],
    "security_facts": [],
    "dividend_facts": [],
    "status": "unavailable",
}


def _identify_dividend_payers(limit=None, reuse_max_age_days=None):
    """Identify dividend-paying tickers among raw.company_ticker via SEC Company Facts.

    SEC Company Facts are fetched once per unique CIK, classified with the
    same rules used by ``scripts.populate_reference_tables``, and persisted to
    ``raw.companyfacts`` immediately so the payload is never downloaded twice
    (stage 4 reuses it) and so it is not held in memory for the whole scan.
    Returns one record per dividend payer with the resolved security types and
    the deterministic security_ids ``scripts.populate_reference_tables`` will
    generate, so the minimal reference.securities rows created here reconcile
    cleanly.

    ``reuse_max_age_days`` bounds how stale a *stored* payload may be and still be
    classified from without re-downloading it. This scan reads all ~10,400
    company tickers on every run, and ``upsert_companyfacts`` re-stamps
    ``retrieved_at = now()`` on every call, so a nightly that fetched each CIK
    unconditionally re-downloaded the entire table every night and reset the
    freshness clock that stages 4a-4c exist to maintain. Reusing recent payloads
    is what the docstring above always claimed ("never downloaded twice") and
    what the offline path below already did; this parameter extends it to the
    online path. ``None`` means always reuse whatever is stored, ``0`` forces a
    re-fetch of everything, and a negative value disables reuse.
    """
    facts_by_cik = {}
    cache_entries = []
    payers = []

    def _reusable(stored_at, now):
        """Is the stored payload fresh enough to classify without re-fetching?"""
        if reuse_max_age_days is None or reuse_max_age_days < 0:
            return False
        if stored_at is None:
            return False
        age = (now - stored_at).total_seconds() / 86400.0
        return age <= reuse_max_age_days

    with engine.connect() as conn:
        observed = observed_payer_keys(conn)
        titles_by_cik = {}
        for title_row in conn.execute(
            text("""
            SELECT cik, ticker, title
            FROM raw.sec_instrument_titles
        """)
        ).mappings():
            titles_by_cik.setdefault(title_row["cik"], {})[str(title_row["ticker"]).upper()] = (
                title_row["title"]
            )

        stored = stored_facts_retrieved_at(conn)
        now = datetime.now(timezone.utc)
        fetched = reused = 0
        for row in _load_raw_tickers(conn, limit):
            cik = row["cik"]
            if cik not in facts_by_cik:
                stored_at = stored.get(cik)
                if _reusable(stored_at, now):
                    # Recent enough to classify from what we already hold: no SEC
                    # request, and crucially no re-stamp of retrieved_at, so this
                    # stage stops resetting the refresh clock stages 4a-4c own.
                    payload = conn.execute(
                        text(
                            "SELECT raw_payload FROM raw.companyfacts "
                            "WHERE cik = :cik AND content_hash IS NOT NULL"
                        ),
                        {"cik": cik},
                    ).scalar()
                    if payload is not None:
                        try:
                            facts_by_cik[cik] = classify_companyfacts(
                                payload, lookback_days=configured_dividend_lookback()
                            )
                            reused += 1
                        except Exception as exc:
                            print(f"  Stored Company Facts unreadable for CIK {cik}: {exc}")
                    if cik not in facts_by_cik:
                        facts_by_cik[cik] = _UNAVAILABLE
                elif OFFLINE_ON:
                    payload = conn.execute(
                        text(
                            "SELECT raw_payload FROM raw.companyfacts "
                            "WHERE cik = :cik AND content_hash IS NOT NULL"
                        ),
                        {"cik": cik},
                    ).scalar()
                    if payload is not None:
                        try:
                            facts_by_cik[cik] = classify_companyfacts(
                                payload, lookback_days=configured_dividend_lookback()
                            )
                        except Exception as exc:
                            print(f"  SEC Company Facts unreadable offline for CIK {cik}: {exc}")
                            facts_by_cik[cik] = {
                                "security_types": ["other"],
                                "dividend": False,
                                "security_titles": [],
                                "security_facts": [],
                                "dividend_facts": [],
                                "status": "unavailable",
                            }
                    else:
                        facts_by_cik[cik] = _UNAVAILABLE
                else:
                    try:
                        facts = get_companyfacts(cik)
                        company_name = facts.get("entityName") if isinstance(facts, dict) else None
                        grouped = build_companyfacts_concept_groups(facts)
                        envelope = {
                            "cik": cik,
                            "company": company_name,
                            **grouped,
                            "full_facts": facts,
                        }
                        upsert_companyfacts(
                            conn,
                            cik,
                            {
                                "cik": cik,
                                "company": company_name,
                                "full_facts": facts,
                                "concept_groups": grouped,
                            },
                        )
                        facts_by_cik[cik] = classify_companyfacts(
                            envelope, lookback_days=configured_dividend_lookback()
                        )
                        fetched += 1
                    except Exception as exc:
                        print(f"  SEC Company Facts unavailable for CIK {cik}: {exc}")
                        facts_by_cik[cik] = _UNAVAILABLE
                    # Commit per CIK. This scan is the longest stage in the nightly
                    # and used to hold one transaction open across all ~10,400 of
                    # them, so a timeout or a suspended host discarded the whole
                    # run -- and a host that suspends is the expected case here.
                    conn.commit()
                cache_entries.append((cik, row["ticker"], row["title"], facts_by_cik[cik]))

            classification = facts_by_cik[cik]
            if not classification["dividend"]:
                if (cik, row["ticker"]) not in observed:
                    continue
                # A payment seen in the stored series keeps the flag when the tags lag it.
                classification = {**classification, "dividend": True}

            exact_title = (titles_by_cik.get(cik) or {}).get(str(row["ticker"]).upper())
            security_type = security_type_for_instrument(
                row["ticker"],
                row["title"],
                classification,
                dei_titles=[exact_title] if exact_title else None,
            )
            security_types = [security_type]
            # Identity is (cik, ticker, security_type); `dividend` is an attribute (V0092).
            security_ids = {}
            for security_type in security_types:
                existing_id = conn.execute(
                    text(
                        "SELECT security_id FROM reference.securities "
                        "WHERE cik = :cik AND ticker = :ticker AND security_type = :type "
                        "ORDER BY active DESC, updated_at DESC LIMIT 1"
                    ),
                    {"cik": cik, "ticker": row["ticker"], "type": security_type},
                ).scalar()
                security_ids[security_type] = existing_id or uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"dividend-equity:{row['ticker'].upper()}:{cik}:{security_type}",
                )
            payers.append(
                {
                    "ticker": row["ticker"],
                    "cik": cik,
                    "title": row["title"],
                    "classification": classification,
                    # SEC's companyfacts JSON never carries dei SecurityTitle/
                    # Security12bTitle -- none of the 7,115 stored payloads do --
                    # so extract_security_titles returns [] for every one of them
                    # and a stored payload cannot add a title the classification
                    # does not already hold. Re-reading it here was a dead 1.8MB
                    # detoast per ticker row; the per-series titles come from the
                    # filing instance (raw.sec_instrument_titles), not this payload.
                    "security_titles": classification.get("security_titles") or [],
                    "security_types": security_types,
                    "security_ids": security_ids,
                }
            )

        _persist_classification_cache(conn, cache_entries)
        conn.commit()

    print(
        f"  Companyfacts payloads: {fetched} fetched, {reused} reused from storage.",
        flush=True,
    )
    return payers


def _upsert_minimal_securities(conn, payer):
    """Create the reference.securities rows referenced by raw.ticker_profile."""
    classification = payer["classification"]
    for security_type in payer["security_types"]:
        # security_id is a hash that includes `dividend`. A legacy row whose flag
        # was flipped in place keeps the old id, so the new key's id collides on
        # securities_security_id_key. Skip it: the instrument already has a
        # current row, and re-keying legacy rows touches 13 child FKs.
        holder = conn.execute(
            text(
                "SELECT cik, ticker, security_type FROM reference.securities "
                "WHERE security_id = :id"
            ),
            {"id": payer["security_ids"][security_type]},
        ).first()
        if holder is not None and tuple(holder) != (
            payer["cik"],
            payer["ticker"],
            security_type,
        ):
            return False
        security_name = match_security_title(
            payer.get("security_titles", []),
            security_type,
            fallback=payer["title"],
        )
        conn.execute(
            text("""
            INSERT INTO reference.securities
            (ticker, cik, security_id, security_name,
             security_type, dividend, dividend_last_paid, sec_data_status, currency, active)
            VALUES (:ticker, :cik, :id, :security_name,
                    :type, :dividend, :dividend_last_paid, :status, 'USD', TRUE)
            ON CONFLICT (cik, ticker, security_type) DO UPDATE SET
                dividend = EXCLUDED.dividend,
                security_name = EXCLUDED.security_name,
                dividend_last_paid = COALESCE(
                    EXCLUDED.dividend_last_paid, reference.securities.dividend_last_paid
                ),
                sec_data_status = EXCLUDED.sec_data_status,
                currency = EXCLUDED.currency,
                active = EXCLUDED.active,
                updated_at = now()
        """),
            {
                "ticker": payer["ticker"],
                "cik": payer["cik"],
                "id": payer["security_ids"][security_type],
                "security_name": security_name,
                "type": security_type,
                "dividend": classification["dividend"],
                "dividend_last_paid": classification.get("dividend_last_paid"),
                "status": classification["status"],
            },
        )
        # Identity is (cik, ticker, security_type). A second active row of the same
        # type with a different id is a superseded identity: retire it. Deactivated,
        # not deleted: raw.ticker_profile may reference it.
        conn.execute(
            text("""
            UPDATE reference.securities
            SET active = FALSE, updated_at = now()
            WHERE cik = :cik AND ticker = :ticker AND active
              AND security_id <> :id
              AND security_type = :type
        """),
            {
                "ticker": payer["ticker"],
                "cik": payer["cik"],
                "id": payer["security_ids"][security_type],
                "type": security_type,
                "dividend": classification["dividend"],
            },
        )
    return True


def populate_ticker_profiles(limit=None, reuse_max_age_days=DEFAULT_REUSE_MAX_AGE_DAYS):
    """Identify dividend payers in raw.company_ticker and populate raw.ticker_profile.

    Fetches a Ticker Profile Summary (via Yahoo Finance / OpenBB) for every
    dividend-paying ticker. A minimal reference.securities row is upserted first
    so the raw.ticker_profile foreign key is satisfied; the reference stage later
    reconciles those rows with full issuer/classification data.
    """
    print("Identifying dividend-paying tickers in raw.company_ticker...")
    payers = _identify_dividend_payers(limit, reuse_max_age_days=reuse_max_age_days)
    print(f"  Identified {len(payers)} dividend-paying tickers.")

    inserted = errors = skipped_legacy = 0
    # Commit per payer rather than once at the end. This loop does network I/O for
    # every payer and takes well over 40 minutes, so a single transaction meant a
    # timeout, crash, or host suspend discarded the entire run: the stage was
    # neither resumable nor observable, and the MAX(retrieved_at) that
    # raw.ticker_profile's freshness check reads could not move until it finished.
    # populate_companyfacts commits per CIK for the same reason.
    with engine.connect() as conn:
        for payer in payers:
            try:
                if OFFLINE_ON:
                    # Air-gapped path: no Yahoo/OpenBB profile fetch. Preferred
                    # terms still come from the SEC XBRL payload already stored.
                    summary = {
                        "ticker": payer["ticker"],
                        "provider": "SEC_XBRL",
                        "sector": None,
                        "industry": None,
                        "security_type": payer["security_types"][0]
                        if payer["security_types"]
                        else None,
                        "coupon_type": None,
                        "coupon_rate": None,
                        "fixed_period_end": None,
                        "floating_spread": None,
                        "tax_status": None,
                        "call_date": None,
                        "liquidation_preference": None,
                        "raw_payload": "{}",
                    }
                else:
                    primary_type = payer["security_types"][0] if payer["security_types"] else None
                    # Parse per-series terms from the security's own title (the
                    # value written to reference.securities.security_name), not
                    # the issuer name, so this writer and populate_dividend_data
                    # derive the same terms for the columns they both own.
                    summary = fetch_ticker_profile(
                        payer["ticker"],
                        security_name=match_security_title(
                            payer.get("security_titles", []),
                            primary_type,
                            fallback=payer["title"],
                        ),
                        security_type=primary_type,
                    )
                sec_terms = {"coupon_rate": None, "liquidation_preference": None}
                # Read this one issuer's payload from the raw cache instead of
                # carrying it through the payers list: holding every companyfacts
                # JSON for the whole scan is what OOM-killed the stage on this host.
                companyfacts = _stored_companyfacts(conn, payer["cik"])
                if companyfacts:
                    try:
                        sec_terms = extract_preferred_terms_from_companyfacts(companyfacts)
                    except Exception as exc:
                        print(f"  Error extracting SEC XBRL terms for {payer['ticker']}: {exc}")

                # SEC Company Facts carry no series/member dimension, and
                # extract_preferred_terms_from_companyfacts falls back to par
                # value when no liquidation-preference concept is filed. The
                # terms therefore describe the issuer (often its common-stock
                # par value) and are kept only as issuer-level evidence in the
                # payload (exposed by preferred.issuer_terms); the per-series
                # columns come solely from the per-security name parse.
                openbb = json.loads(summary.get("raw_payload") or "{}")
                summary["raw_payload"] = envelope_payload(
                    openbb=openbb,
                    sec_xbrl=sec_terms,
                    sec_xbrl_scope=SEC_XBRL_SCOPE,
                )
                if OFFLINE_ON:
                    # Offline rows only fill a brand-new profile; they own no
                    # column, so they never overwrite an online observation.
                    owned_columns = ()
                else:
                    summary["provider"] = "SEC_XBRL+OPENBB_YFINANCE" if openbb else "SEC_XBRL"
                    # Name-parse terms are deterministic for the title, so
                    # they own their columns (NULL clears a stale value).
                    # OpenBB columns are owned only when OpenBB answered, so a
                    # failed fetch does not erase sector/industry.
                    owned_columns = NAME_PARSE_COLUMNS + (OPENBB_COLUMNS if openbb else ())

                if _upsert_minimal_securities(conn, payer) is False:
                    skipped_legacy += 1
                    conn.rollback()
                    continue
                row = {"security_id": payer["security_ids"][payer["security_types"][0]], **summary}
                upsert_ticker_profile(
                    conn, row, loader="populate_raw_tables", owned_columns=owned_columns
                )
                conn.execute(
                    text("""
                    UPDATE reference.securities
                    SET coupon_rate = COALESCE(:coupon_rate, coupon_rate),
                        liquidation_preference = COALESCE(
                            :liquidation_preference, liquidation_preference
                        ),
                        call_date = COALESCE(:call_date, call_date),
                        updated_at = now()
                    WHERE security_id = :security_id
                """),
                    row,
                )
                inserted += 1
                conn.commit()
                if inserted % 250 == 0:
                    print(
                        f"  Progress: {inserted}/{len(payers)} payers, errors={errors}",
                        flush=True,
                    )
            except Exception as exc:
                errors += 1
                # Postgres aborts the entire transaction on a failed statement, so
                # without this rollback every later payer would fail with
                # "current transaction is aborted" -- one bad row would take out
                # the remaining ~5,700 as collateral.
                conn.rollback()
                if errors <= 5:
                    print(f"  Error populating profile for {payer['ticker']}: {exc}")

    print("\n✓ Populated raw.ticker_profile:")
    print(f"  Identified: {len(payers)} dividend payers")
    print(f"  Inserted/refreshed: {inserted}")
    print(f"  Errors: {errors}")
    if skipped_legacy:
        print(f"  Skipped (security_id held by a legacy row): {skipped_legacy}")
    return len(payers), inserted, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to first N records (for testing)"
    )
    parser.add_argument(
        "--skip-profiles",
        action="store_true",
        help="Only populate raw.company_ticker; skip ticker profiles",
    )

    parser.add_argument(
        "--reuse-max-age-days",
        type=float,
        default=DEFAULT_REUSE_MAX_AGE_DAYS,
        help="Classify from an already-stored companyfacts payload when it is "
        f"younger than this many days, instead of re-downloading it (default "
        f"{DEFAULT_REUSE_MAX_AGE_DAYS}). This scan reads every company ticker on "
        "every run; without reuse it re-downloaded the whole table nightly, "
        "~10,400 requests, and reset raw.companyfacts.retrieved_at each time, "
        "hiding whether the refresh stages are actually keeping it current. Use 0 "
        "to force a re-fetch of everything, or a negative value to disable reuse.",
    )

    args = parser.parse_args()

    try:
        refresh = populate_company_tickers(args.limit)
        report_ticker_conflicts(refresh.conflicts)
        # An empty company_ticker snapshot is a total failure, not an empty
        # universe: reference.securities is built from this table, so returning
        # success here leaves every downstream stage reading nothing. Conflicts are
        # deliberately not passed as ``skipped``: a run in which every ticker
        # conflicted wrote nothing and has to fail like any other empty write.
        code = stage_exit_code(
            "populate_raw_tables (company_ticker)", refresh.seen, refresh.ingested
        )
        if code:
            return code
        outcome = (
            f"completed with warnings ({len(refresh.conflicts)} ticker/CIK conflict(s) skipped)"
            if refresh.conflicts
            else "populated successfully"
        )
        if args.skip_profiles:
            print(f"\n✓ Raw tables {outcome}! (profiles skipped)")
        else:
            payers, inserted, errors = populate_ticker_profiles(
                args.limit, reuse_max_age_days=args.reuse_max_age_days
            )
            code = stage_exit_code(
                "populate_raw_tables (ticker_profile)", payers, inserted, errors=errors
            )
            if code:
                return code
            print(f"\n✓ Raw tables {outcome}!")
        return 0

    except Exception as e:
        print(f"\n✗ Error populating raw tables: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
