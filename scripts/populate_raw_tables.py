"""
Populate raw schema tables with SEC API data.

Currently populates raw.company_ticker with the SEC company_tickers.json
snapshot, identifies which tickers issue a dividend, and writes a Ticker
Profile Summary for each dividend payer into raw.ticker_profile.

Dividend payers are identified from SEC Company Facts (the same XBRL
classification used by scripts.populate_reference_tables). The same SEC
Company Facts payload is then mined for preferred-stock coupon_rate and
liquidation_preference XBRL tags (see
src.crispdm.sec_client.extract_preferred_terms_from_companyfacts); those SEC
values take priority over the Yahoo Finance / OpenBB profile fetched by
scripts.populate_dividend_data.fetch_ticker_profile, which only fills in
sector/industry/tax_status/call_date and other fields SEC XBRL does not
reliably expose. A minimal reference.securities row is created for each payer
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

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts.populate_companyfacts import (
    stored_facts_retrieved_at,
    upsert_companyfacts,
)
from scripts.populate_dividend_data import fetch_ticker_profile
from src.crispdm.db import engine
from src.crispdm.sec_client import (
    build_companyfacts_concept_groups,
    classify_companyfacts,
    configured_dividend_lookback,
    extract_preferred_terms_from_companyfacts,
    extract_security_titles,
    get_company_tickers,
    get_companyfacts,
    match_security_title,
    security_type_for_instrument,
)
from src.crispdm.stage import stage_exit_code


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()


def _refresh_company_tickers(conn, entries):
    """Apply the raw.company_ticker snapshot: FK guard + per-ticker upsert."""
    conn.execute(
        text("ALTER TABLE raw.company_ticker DROP CONSTRAINT IF EXISTS company_ticker_cik_key")
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "ux_company_ticker_ticker_cik ON raw.company_ticker(ticker, cik)"
        )
    )
    conn.execute(
        text("ALTER TABLE reference.securities DROP CONSTRAINT IF EXISTS securities_cik_fkey")
    )
    conn.execute(
        text(
            "ALTER TABLE reference.securities "
            "DROP CONSTRAINT IF EXISTS fk_securities_company_ticker"
        )
    )
    conn.execute(
        text("""
        ALTER TABLE reference.securities
        ADD CONSTRAINT fk_securities_company_ticker
        FOREIGN KEY (ticker, cik)
        REFERENCES raw.company_ticker(ticker, cik)
        NOT VALID
    """)
    )

    for entry in entries:
        ticker = (entry.get("ticker") or "").strip().upper()
        if not ticker or entry.get("cik_str") is None:
            continue
        cik = str(int(entry["cik_str"])).zfill(10)
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
                "title": (entry.get("title") or "").strip(),
                "raw_payload": json.dumps(entry),
            },
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
            _refresh_company_tickers(conn, entries)
        print(f"  Populated {len(entries)} raw company ticker records (offline).")
        return len(entries)

    tickers_data = get_company_tickers()
    entries = list(tickers_data.values())
    if limit:
        entries = entries[:limit]

    with engine.begin() as conn:
        _refresh_company_tickers(conn, entries)

    print(f"  Populated {len(entries)} raw company ticker records.")
    return len(entries)


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
                continue

            exact_title = (titles_by_cik.get(cik) or {}).get(str(row["ticker"]).upper())
            security_type = security_type_for_instrument(
                row["ticker"],
                row["title"],
                classification,
                dei_titles=[exact_title] if exact_title else None,
            )
            security_types = [security_type]
            security_ids = {
                security_type: uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"dividend-equity:{row['ticker'].upper()}:{cik}:{security_type}:{classification['dividend']}",
                )
                for security_type in security_types
            }
            stored_payload = None if OFFLINE_ON else _stored_companyfacts(conn, cik)
            payers.append(
                {
                    "ticker": row["ticker"],
                    "cik": cik,
                    "title": row["title"],
                    "classification": classification,
                    "security_titles": classification.get("security_titles")
                    or (extract_security_titles(stored_payload) if stored_payload else []),
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
                "SELECT cik, ticker, security_type, dividend FROM reference.securities "
                "WHERE security_id = :id"
            ),
            {"id": payer["security_ids"][security_type]},
        ).first()
        if holder is not None and tuple(holder) != (
            payer["cik"],
            payer["ticker"],
            security_type,
            classification["dividend"],
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
            ON CONFLICT (cik, ticker, security_type, dividend) DO UPDATE SET
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
        # The key carries `dividend` and `security_type`, so a flipped flag mints
        # a new row beside the old one. Retire the older twin now rather than
        # leaving two active rows until the reference stage reconciles them
        # (V0047). Deactivated, not deleted: raw.ticker_profile may reference it.
        conn.execute(
            text("""
            UPDATE reference.securities
            SET active = FALSE, updated_at = now()
            WHERE cik = :cik AND ticker = :ticker AND active
              AND security_id <> :id
              AND (security_type, dividend) IS DISTINCT FROM (:type, :dividend)
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
                    summary = fetch_ticker_profile(
                        payer["ticker"],
                        security_name=payer["title"],
                        security_type=payer["security_types"][0]
                        if payer["security_types"]
                        else None,
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

                # Coupon precedence is deliberate, not a side effect of stage
                # order: the per-security name parse (dei:SecurityTitle /
                # short_name) is the primary source because it is instrument
                # specific, and SEC XBRL terms are the fallback for issuers
                # whose title carries no parsable rate. SEC terms are read from
                # the issuer's companyfacts, so they are only correct for a
                # single-series issuer; overwriting a good per-security parse
                # with them mislabels multi-series issuers.
                if sec_terms.get("coupon_rate") is not None and summary.get("coupon_rate") is None:
                    summary["coupon_rate"] = sec_terms["coupon_rate"]
                if sec_terms.get("liquidation_preference") is not None:
                    summary["liquidation_preference"] = sec_terms["liquidation_preference"]

                if not OFFLINE_ON:
                    summary["provider"] = "SEC_XBRL+OPENBB_YFINANCE"
                summary["raw_payload"] = json.dumps(
                    {
                        "sec_xbrl": sec_terms,
                        "openbb": json.loads(summary["raw_payload"])
                        if summary.get("raw_payload")
                        else None,
                    },
                    default=str,
                )

                if _upsert_minimal_securities(conn, payer) is False:
                    skipped_legacy += 1
                    conn.rollback()
                    continue
                row = {"security_id": payer["security_ids"][payer["security_types"][0]], **summary}
                conn.execute(
                    text("""
                    INSERT INTO raw.ticker_profile AS current_profile
                        (security_id, ticker, provider, sector, industry, security_type,
                         coupon_type, coupon_rate, fixed_period_end, floating_spread,
                         tax_status, call_date, liquidation_preference, raw_payload, retrieved_at)
                    VALUES (:security_id, :ticker, :provider, :sector, :industry,
                            :security_type, :coupon_type, :coupon_rate, :fixed_period_end,
                            :floating_spread, :tax_status, :call_date,
                            :liquidation_preference, CAST(:raw_payload AS jsonb), now())
                    ON CONFLICT (security_id) DO UPDATE SET
                        ticker = EXCLUDED.ticker,
                        provider = CASE
                            WHEN current_profile.provider = EXCLUDED.provider THEN EXCLUDED.provider
                            WHEN current_profile.provider IN (
                                'SEC_XBRL', 'OPENBB_YFINANCE', 'SEC_XBRL+OPENBB_YFINANCE'
                            ) AND EXCLUDED.provider IN (
                                'SEC_XBRL', 'OPENBB_YFINANCE', 'SEC_XBRL+OPENBB_YFINANCE'
                            ) THEN 'SEC_XBRL+OPENBB_YFINANCE'
                            ELSE EXCLUDED.provider
                        END,
                        sector = COALESCE(EXCLUDED.sector, current_profile.sector),
                        industry = COALESCE(EXCLUDED.industry, current_profile.industry),
                        security_type = COALESCE(EXCLUDED.security_type, current_profile.security_type),
                        coupon_type = COALESCE(EXCLUDED.coupon_type, current_profile.coupon_type),
                        coupon_rate = COALESCE(EXCLUDED.coupon_rate, current_profile.coupon_rate),
                        fixed_period_end = COALESCE(
                            EXCLUDED.fixed_period_end, current_profile.fixed_period_end
                        ),
                        floating_spread = COALESCE(
                            EXCLUDED.floating_spread, current_profile.floating_spread
                        ),
                        tax_status = COALESCE(EXCLUDED.tax_status, current_profile.tax_status),
                        call_date = COALESCE(EXCLUDED.call_date, current_profile.call_date),
                        liquidation_preference = COALESCE(
                            EXCLUDED.liquidation_preference,
                            current_profile.liquidation_preference
                        ),
                        raw_payload = COALESCE(current_profile.raw_payload, '{}'::jsonb)
                                     || EXCLUDED.raw_payload,
                        retrieved_at = now()
                """),
                    row,
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
        tickers = populate_company_tickers(args.limit)
        # An empty company_ticker snapshot is a total failure, not an empty
        # universe: reference.securities is built from this table, so returning
        # success here leaves every downstream stage reading nothing.
        code = stage_exit_code("populate_raw_tables (company_ticker)", tickers, tickers)
        if code:
            return code
        if args.skip_profiles:
            print("\n✓ Raw tables populated successfully! (profiles skipped)")
        else:
            payers, inserted, errors = populate_ticker_profiles(
                args.limit, reuse_max_age_days=args.reuse_max_age_days
            )
            code = stage_exit_code(
                "populate_raw_tables (ticker_profile)", payers, inserted, errors=errors
            )
            if code:
                return code
            print("\n✓ Raw tables populated successfully!")
        return 0

    except Exception as e:
        print(f"\n✗ Error populating raw tables: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
