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
from pathlib import Path
import sys
import uuid

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from src.crispdm.db import engine
from src.crispdm.sec_client import (
    classify_companyfacts,
    extract_preferred_terms_from_companyfacts,
    extract_security_titles,
    get_companyfacts_concepts,
    get_company_tickers,
    match_security_title,
    security_type_for_instrument,
)
from scripts.populate_dividend_data import fetch_ticker_profile


def _offline_enabled():
    return os.environ.get("SEC_ETL_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


OFFLINE_ON = _offline_enabled()


def _refresh_company_tickers(conn, entries):
    """Apply the raw.company_ticker snapshot: FK guard + per-ticker upsert."""
    conn.execute(text(
        "ALTER TABLE raw.company_ticker "
        "DROP CONSTRAINT IF EXISTS company_ticker_cik_key"
    ))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_company_ticker_ticker_cik ON raw.company_ticker(ticker, cik)"
    ))
    conn.execute(text(
        "ALTER TABLE reference.securities "
        "DROP CONSTRAINT IF EXISTS securities_cik_fkey"
    ))
    conn.execute(text(
        "ALTER TABLE reference.securities "
        "DROP CONSTRAINT IF EXISTS fk_securities_company_ticker"
    ))
    conn.execute(text("""
        ALTER TABLE reference.securities
        ADD CONSTRAINT fk_securities_company_ticker
        FOREIGN KEY (ticker, cik)
        REFERENCES raw.company_ticker(ticker, cik)
        NOT VALID
    """))

    for entry in entries:
        ticker = (entry.get("ticker") or "").strip().upper()
        if not ticker or entry.get("cik_str") is None:
            continue
        cik = str(int(entry["cik_str"])).zfill(10)
        conn.execute(text("""
            INSERT INTO raw.company_ticker
                (ticker, cik, title, raw_payload, retrieved_at)
            VALUES (:ticker, :cik, :title, CAST(:raw_payload AS jsonb), now())
            ON CONFLICT (ticker) DO UPDATE SET
                cik = EXCLUDED.cik,
                title = EXCLUDED.title,
                raw_payload = EXCLUDED.raw_payload,
                retrieved_at = EXCLUDED.retrieved_at
        """), {
            "ticker": ticker,
            "cik": cik,
            "title": (entry.get("title") or "").strip(),
            "raw_payload": json.dumps(entry),
        })


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
            rows = conn.execute(text(
                "SELECT ticker, cik, title FROM raw.company_ticker ORDER BY ticker"
            )).mappings().all()
            entries = [
                {"ticker": r["ticker"], "cik_str": r["cik"], "title": r["title"]}
                for r in rows
            ]
            if limit:
                entries = entries[:limit]
            _refresh_company_tickers(conn, entries)
        print(f"  Populated {len(entries)} raw company ticker records (offline).")
        return

    tickers_data = get_company_tickers()
    entries = list(tickers_data.values())
    if limit:
        entries = entries[:limit]

    with engine.begin() as conn:
        _refresh_company_tickers(conn, entries)

    print(f"  Populated {len(entries)} raw company ticker records.")


def _load_raw_tickers(conn, limit=None):
    """Load ticker/cik/title rows from raw.company_ticker."""
    limit_sql = " LIMIT :limit" if limit else ""
    params = {"limit": limit} if limit else {}
    return conn.execute(text(f"""
        SELECT ticker, cik, title
        FROM raw.company_ticker
        ORDER BY ticker
        {limit_sql}
    """), params).mappings().all()


def _persist_classification_cache(conn, entries):
    """Persist the compact per-CIK classification cache computed in stage 0.

    Later stages (populate_reference_tables, populate_companyfacts) read this
    cache instead of re-downloading the full SEC companyfacts payload per CIK,
    avoiding the duplicate loads that previously made the ETL slow and the
    storage inefficient.
    """
    for cik, ticker, title, classification in entries:
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
            "company_name": title,
            "security_types": json.dumps(classification["security_types"]),
            "security_titles": json.dumps(classification.get("security_titles", [])),
            "security_facts": json.dumps(classification["security_facts"]),
            "dividend_facts": json.dumps(classification["dividend_facts"]),
            "dividend": classification["dividend"],
            "status": classification["status"],
            "content_hash": hashlib.sha256(
                json.dumps(
                    classification["dividend_facts"], sort_keys=True
                ).encode("utf-8")
            ).hexdigest(),
        })


def _identify_dividend_payers(limit=None):
    """Identify dividend-paying tickers among raw.company_ticker via SEC Company Facts.

    SEC Company Facts are fetched once per unique CIK and classified with the
    same rules used by ``scripts.populate_reference_tables``. Returns one record
    per dividend payer with the resolved security types and the deterministic
    security_ids ``scripts.populate_reference_tables`` will generate, so the
    minimal reference.securities rows created here reconcile cleanly.
    """
    facts_by_cik = {}
    companyfacts_by_cik = {}
    cache_entries = []
    payers = []

    with engine.connect() as conn:
        titles_by_cik = {}
        for title_row in conn.execute(text("""
            SELECT cik, ticker, title
            FROM raw.sec_instrument_titles
        """)).mappings():
            titles_by_cik.setdefault(title_row["cik"], {})[
                str(title_row["ticker"]).upper()
            ] = title_row["title"]

        for row in _load_raw_tickers(conn, limit):
            cik = row["cik"]
            if cik not in facts_by_cik:
                if OFFLINE_ON:
                    payload = conn.execute(
                        text(
                            "SELECT raw_payload FROM raw.companyfacts "
                            "WHERE cik = :cik AND content_hash IS NOT NULL"
                        ),
                        {"cik": cik},
                    ).scalar()
                    if payload is not None:
                        try:
                            facts_by_cik[cik] = classify_companyfacts(payload)
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
                        facts_by_cik[cik] = {
                            "security_types": ["other"],
                            "dividend": False,
                            "security_titles": [],
                            "security_facts": [],
                            "dividend_facts": [],
                            "status": "unavailable",
                        }
                else:
                    try:
                        concepts = get_companyfacts_concepts(cik)
                        companyfacts_by_cik[cik] = concepts
                        facts_by_cik[cik] = classify_companyfacts(concepts)
                    except Exception as exc:
                        print(f"  SEC Company Facts unavailable for CIK {cik}: {exc}")
                        companyfacts_by_cik[cik] = None
                        facts_by_cik[cik] = {
                            "security_types": ["other"],
                            "dividend": False,
                            "security_titles": [],
                            "security_facts": [],
                            "dividend_facts": [],
                            "status": "unavailable",
                        }
                cache_entries.append(
                    (cik, row["ticker"], row["title"], facts_by_cik[cik])
                )

            classification = facts_by_cik[cik]
            if not classification["dividend"]:
                continue

            exact_title = (titles_by_cik.get(cik) or {}).get(
                str(row["ticker"]).upper()
            )
            security_type = security_type_for_instrument(
                row["ticker"], row["title"], classification,
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
            payers.append({
                "ticker": row["ticker"],
                "cik": cik,
                "title": row["title"],
                "classification": classification,
                "companyfacts": companyfacts_by_cik.get(cik),
                "security_titles": classification.get("security_titles")
                or extract_security_titles(companyfacts_by_cik[cik])
                if companyfacts_by_cik.get(cik) else [],
                "security_types": security_types,
                "security_ids": security_ids,
            })

        _persist_classification_cache(conn, cache_entries)
        conn.commit()

    return payers


def _upsert_minimal_securities(conn, payer):
    """Create the reference.securities rows referenced by raw.ticker_profile."""
    classification = payer["classification"]
    for security_type in payer["security_types"]:
        security_name = match_security_title(
            payer.get("security_titles", []),
            security_type,
            fallback=payer["title"],
        )
        conn.execute(text("""
            INSERT INTO reference.securities
            (ticker, cik, security_id, security_name,
             security_type, dividend, sec_data_status, currency, active)
            VALUES (:ticker, :cik, :id, :security_name,
                    :type, :dividend, :status, 'USD', TRUE)
            ON CONFLICT (cik, ticker, security_type, dividend) DO UPDATE SET
                security_name = EXCLUDED.security_name,
                sec_data_status = EXCLUDED.sec_data_status,
                currency = EXCLUDED.currency,
                active = EXCLUDED.active,
                updated_at = now()
        """), {
            "ticker": payer["ticker"],
            "cik": payer["cik"],
            "id": payer["security_ids"][security_type],
            "security_name": security_name,
            "type": security_type,
            "dividend": classification["dividend"],
            "status": classification["status"],
        })


def populate_ticker_profiles(limit=None):
    """Identify dividend payers in raw.company_ticker and populate raw.ticker_profile.

    Fetches a Ticker Profile Summary (via Yahoo Finance / OpenBB) for every
    dividend-paying ticker. A minimal reference.securities row is upserted first
    so the raw.ticker_profile foreign key is satisfied; the reference stage later
    reconciles those rows with full issuer/classification data.
    """
    print("Identifying dividend-paying tickers in raw.company_ticker...")
    payers = _identify_dividend_payers(limit)
    print(f"  Identified {len(payers)} dividend-paying tickers.")

    inserted = errors = 0
    with engine.begin() as conn:
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
                        if payer["security_types"] else None,
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
                        if payer["security_types"] else None,
                    )
                sec_terms = {"coupon_rate": None, "liquidation_preference": None}
                companyfacts = payer["companyfacts"]
                if OFFLINE_ON:
                    # Re-fetch just this payer's payload: keep memory bounded.
                    companyfacts = conn.execute(
                        text(
                            "SELECT raw_payload FROM raw.companyfacts "
                            "WHERE cik = :cik AND content_hash IS NOT NULL"
                        ),
                        {"cik": payer["cik"]},
                    ).scalar()
                if companyfacts:
                    try:
                        sec_terms = extract_preferred_terms_from_companyfacts(companyfacts)
                    except Exception as exc:
                        print(f"  Error extracting SEC XBRL terms for {payer['ticker']}: {exc}")

                # SEC Company Facts XBRL is the authoritative source; only fall
                # back to the Yahoo/OpenBB or name-parsed value when SEC has none.
                if sec_terms.get("coupon_rate") is not None:
                    summary["coupon_rate"] = sec_terms["coupon_rate"]
                if sec_terms.get("liquidation_preference") is not None:
                    summary["liquidation_preference"] = sec_terms["liquidation_preference"]

                if not OFFLINE_ON:
                    summary["provider"] = "SEC_XBRL+OPENBB_YFINANCE"
                summary["raw_payload"] = json.dumps({
                    "sec_xbrl": sec_terms,
                    "openbb": json.loads(summary["raw_payload"]) if summary.get("raw_payload") else None,
                }, default=str)

                _upsert_minimal_securities(conn, payer)
                row = {"security_id": payer["security_ids"][payer["security_types"][0]], **summary}
                conn.execute(text("""
                    INSERT INTO raw.ticker_profile
                        (security_id, ticker, provider, sector, industry, security_type,
                         coupon_type, coupon_rate, fixed_period_end, floating_spread,
                         tax_status, call_date, liquidation_preference, raw_payload, retrieved_at)
                    VALUES (:security_id, :ticker, :provider, :sector, :industry,
                            :security_type, :coupon_type, :coupon_rate, :fixed_period_end,
                            :floating_spread, :tax_status, :call_date,
                            :liquidation_preference, CAST(:raw_payload AS jsonb), now())
                    ON CONFLICT (security_id) DO UPDATE SET
                        ticker = EXCLUDED.ticker,
                        provider = EXCLUDED.provider,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        security_type = EXCLUDED.security_type,
                        coupon_type = EXCLUDED.coupon_type,
                        coupon_rate = EXCLUDED.coupon_rate,
                        fixed_period_end = EXCLUDED.fixed_period_end,
                        floating_spread = EXCLUDED.floating_spread,
                        tax_status = EXCLUDED.tax_status,
                        call_date = EXCLUDED.call_date,
                        liquidation_preference = EXCLUDED.liquidation_preference,
                        raw_payload = EXCLUDED.raw_payload,
                        retrieved_at = now()
                """), row)
                conn.execute(text("""
                    UPDATE reference.securities
                    SET coupon_rate = COALESCE(:coupon_rate, coupon_rate),
                        liquidation_preference = COALESCE(
                            :liquidation_preference, liquidation_preference
                        ),
                        call_date = COALESCE(:call_date, call_date),
                        updated_at = now()
                    WHERE security_id = :security_id
                """), row)
                inserted += 1
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  Error populating profile for {payer['ticker']}: {exc}")

    print("\n✓ Populated raw.ticker_profile:")
    print(f"  Identified: {len(payers)} dividend payers")
    print(f"  Inserted/refreshed: {inserted}")
    print(f"  Errors: {errors}")
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to first N records (for testing)")
    parser.add_argument("--skip-profiles", action="store_true",
                        help="Only populate raw.company_ticker; skip ticker profiles")

    args = parser.parse_args()

    try:
        populate_company_tickers(args.limit)
        if args.skip_profiles:
            print("\n✓ Raw tables populated successfully! (profiles skipped)")
        else:
            populate_ticker_profiles(args.limit)
            print("\n✓ Raw tables populated successfully!")
        return 0

    except Exception as e:
        print(f"\n✗ Error populating raw tables: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())