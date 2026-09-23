"""
Populate raw.dividend_data for all companies that issued a dividend, then load
a Ticker Profile Summary for every dividend-paying equity.

Ticker Profile Summary captures per security:
    Security Type          e.g. Series C Preferred Stock
    Coupon Type            e.g. fixed, floating, fixed-to-floating
    Coupon Rate            e.g. 8.625 (% per annum)
    Fixed Period End       e.g. 7/30/2024 (end of the fixed-rate period)
    Floating Spread        e.g. 5.375 (bps-equivalent spread over SONIA/SOFR)
    Tax Status             e.g. qualified, non-qualified, tax-exempt
    Call Date              e.g. 7/30/2024 (post-call)
    Liquidation Preference e.g. $25 par value

Profiles are fetched by Yahoo Finance / OpenBB (yfinance provider:
obb.equity.profile plus yfinance quote info) and written to raw.ticker_profile.
The target list comes from raw.company_ticker; only tickers flagged
dividend = TRUE in reference.securities are fetched, so non-payers are never
queried. preferred.security_terms is also populated for preferred securities.

Usage:
    python -m scripts.populate_dividend_data [--limit N] [--tickers SYMBOL,SYMBOL,...] [--sources all|sec|openbb]

Options:
    --limit N              Limit to the first N companies for testing
    --tickers SYMBOL,...   Populate only selected tickers
    --sources VALUE        one of: all, sec, openbb (default: all)
    --start-date YYYY-MM-DD
    --end-date YYYY-MM-DD
    --skip-preferred-terms Do not populate preferred.security_terms after loading dividends
    --skip-profiles        Do not fetch/store raw.ticker_profile summaries for dividend payers
    --include-non-dividend Also fetch dividend events for securities not flagged dividend=TRUE
                           (default: restricted to the reference.securities dividend universe)

Examples:
    python -m scripts.populate_dividend_data --sources all --tickers AAPL,MSFT,JNJ
    python -m scripts.populate_dividend_data --limit 10 --sources sec
    python -m scripts.populate_dividend_data --sources openbb --tickers ACR-PC,ACR-PD
"""
import argparse
import json
import re
import sys
from datetime import datetime, date, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.sec_client import (
    build_companyfacts_concept_groups,
    get_companyfacts,
    get_company_tickers,
)
from scripts.populate_companyfacts import upsert_companyfacts

try:
    from src.crispdm.openbb_client import dividends as openbb_dividends
    from src.crispdm.openbb_client import stock_summary as openbb_stock_summary
except Exception:  # pragma: no cover - optional dependency
    openbb_dividends = None
    openbb_stock_summary = None

PROFILE_PROVIDER = "OPENBB_YFINANCE"


def safe_float(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_date(value):
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if "T" in value:
            value = value.split("T", 1)[0]
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


SEC_DIVIDEND_CONCEPTS = (
    "CommonStockDividendsPaid",
    "CommonStockDividendsPerShareDeclared",
    "PreferredStockDividendsPaid",
    "DividendsCashPaid",
    "DividendsCommonStockCash",
    "StockIssuedDuringPeriodValueCommonStockDividends",
)


def _companyfacts_for_dividends(cik, conn):
    """Reuse a stored companyfacts payload or fetch + cache it (one row per CIK).

    The raw.companyfacts row is keyed by issuer CIK and shared by every listed
    security of the issuer. Caching here means the later companyfacts stage
    (scripts.populate_companyfacts) reuses this payload instead of downloading
    the same SEC JSON a second time.
    """
    cik = str(int(cik)).zfill(10)
    stored = conn.execute(text(
        "SELECT raw_payload FROM raw.companyfacts WHERE cik = :cik"
    ), {"cik": cik}).scalar()
    if stored is not None:
        return stored

    facts = get_companyfacts(cik)
    grouped = build_companyfacts_concept_groups(facts)
    envelope = {
        "cik": cik,
        "company": facts.get("entityName") if isinstance(facts, dict) else None,
        "full_facts": facts,
        **grouped,
    }
    upsert_companyfacts(conn, cik, envelope)
    conn.commit()
    return facts


def extract_sec_dividend_data(cik, conn=None):
    """Extract dividend payment/declaration records from SEC XBRL company facts.

    Returns rows keyed by concept, unit currency, and the XBRL filing period
    (``end``) used as the ex-dividend/payment date proxy. The live SEC
    companyfacts endpoint nests taxonomies under ``facts``; older cached or
    test payloads keep them at the root, so accept both shapes. Payloads are
    read from / written into raw.companyfacts so the issuer JSON is never
    downloaded twice across the dividend-data and companyfacts stages.
    """
    own_conn = conn is None
    if own_conn:
        conn = engine.connect()
    rows = []
    try:
        facts = _companyfacts_for_dividends(cik, conn)

        taxonomies = facts.get("facts") if isinstance(facts, dict) else facts
        if not isinstance(taxonomies, dict):
            taxonomies = facts if isinstance(facts, dict) else {}
        us_gaap = taxonomies.get("us-gaap", {}) if isinstance(taxonomies, dict) else {}

        for concept_name in SEC_DIVIDEND_CONCEPTS:
            concept = us_gaap.get(concept_name, {}) if isinstance(us_gaap, dict) else {}
            if not isinstance(concept, dict):
                continue
            for unit_type, unit_values in (concept.get("units") or {}).items():
                if not isinstance(unit_values, list):
                    unit_values = [unit_values]
                for record in unit_values:
                    if not isinstance(record, dict):
                        continue
                    try:
                        amount = float(record.get("val", 0))
                    except (TypeError, ValueError):
                        continue
                    if amount <= 0:
                        continue
                    end = record.get("end")
                    rows.append({
                        "cik": str(int(cik)).zfill(10),
                        "concept": concept_name,
                        "ex_dividend_date": end,
                        "declaration_date": None,
                        "record_date": None,
                        "payment_date": end,
                        "amount": amount,
                        "frequency": "Annual",
                        "currency": "USD" if "USD" in unit_type else unit_type,
                        "filed_date": record.get("filed"),
                        "form": record.get("form", ""),
                        "accn": record.get("accn", ""),
                    })
    except Exception as exc:
        print(f"Error extracting company facts for CIK {cik}: {exc}")
    finally:
        if own_conn:
            conn.close()
    return rows


def normalize_sec_dividend_rows(ticker, sec_rows):
    normalized = []
    for row in sec_rows or []:
        amount = safe_float(row.get("amount"))
        if amount is None or amount <= 0:
            continue
        normalized.append({
            "ticker": ticker,
            "provider": "SEC_XBRL",
            "cik": row.get("cik"),
            "ex_dividend_date": parse_date(row.get("ex_dividend_date")),
            "declaration_date": parse_date(row.get("declaration_date")),
            "record_date": parse_date(row.get("record_date")),
            "payment_date": parse_date(row.get("payment_date")),
            "amount": amount,
            "adjusted_amount": safe_float(row.get("adjusted_amount")),
            "frequency": (row.get("frequency") or "Annual").strip() or "Annual",
            "currency": (row.get("currency") or "USD").upper(),
        })
    return normalized


def normalize_openbb_dividend_rows(ticker, data_frame):
    normalized = []
    if data_frame is None:
        return normalized

    df = data_frame.copy()
    if hasattr(df, "columns"):
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    for _, row in df.iterrows():
        amount = (
            safe_float(row.get("amount"))
            or safe_float(row.get("dividend_amount"))
            or safe_float(row.get("cash_dividend"))
            or safe_float(row.get("dividends"))
        )
        if amount is None or amount <= 0:
            continue

        normalized.append({
            "ticker": ticker,
            "provider": "OPENBB",
            "ex_dividend_date": parse_date(
                row.get("ex_dividend_date")
                or row.get("date")
                or row.get("payment_date")
            ),
            "declaration_date": parse_date(row.get("declaration_date")),
            "record_date": parse_date(row.get("record_date")),
            "payment_date": parse_date(row.get("payment_date") or row.get("date")),
            "amount": amount,
            "adjusted_amount": (
                safe_float(row.get("adjusted_amount"))
                or safe_float(row.get("adj_amount"))
                or safe_float(row.get("adjusted_dividend"))
            ),
            "frequency": (row.get("frequency") or row.get("period") or "Annual").strip() or "Annual",
            "currency": (row.get("currency") or "USD").upper(),
        })

    return normalized


def merge_dividend_records(records):
    merged = {}
    for record in records:
        key = (
            record.get("ticker"),
            record.get("provider"),
            str(record.get("ex_dividend_date") or ""),
            str(record.get("payment_date") or ""),
        )
        if key not in merged:
            merged[key] = record
            continue

        existing = merged[key]
        existing_amount = existing.get("amount")
        new_amount = record.get("amount")
        if new_amount is not None and (existing_amount is None or new_amount > existing_amount):
            merged[key] = record
    return list(merged.values())


def get_target_tickers(limit=None, tickers=None, ticker_map=None):
    if tickers:
        return [t.strip().upper() for t in tickers if t and t.strip()]

    if ticker_map is not None:
        records = list(ticker_map)
    else:
        all_tickers = list(get_company_tickers().values())
        records = [entry.get("ticker") for entry in all_tickers if entry.get("ticker")]
    if limit is not None:
        return records[:limit]
    return records


def get_sec_ticker_map():
    """Load the SEC ticker file once and return normalized ticker-to-CIK values."""
    return {
        (entry.get("ticker") or "").strip().upper(): entry.get("cik_str")
        for entry in get_company_tickers().values()
        if entry.get("ticker") and entry.get("cik_str") is not None
    }


def get_target_dividend_tickers(conn, tickers=None, dividend_only=True, limit=None):
    """Resolve the dividend universe to fetch dividend events for.

    Returns active reference-securities tickers. By default only
    ``dividend = TRUE`` securities are returned so SEC XBRL and OpenBB requests
    are never made for tickers that do not pay a dividend. Explicit ``tickers``
    are intersected with the universe (unless ``dividend_only`` is False).
    """
    filters = ["s.active = TRUE"]
    params = {}
    if dividend_only:
        filters.append("s.dividend = TRUE")
    where = " AND ".join(filters)
    rows = conn.execute(text(f"""
        SELECT DISTINCT ON (s.ticker) s.ticker
        FROM reference.securities s
        WHERE {where}
        ORDER BY s.ticker, s.updated_at DESC NULLS LAST
    """), params).mappings().all()
    universe = [row["ticker"] for row in rows]

    if tickers:
        requested = {ticker.upper() for ticker in tickers}
        if dividend_only:
            result = [ticker for ticker in universe if ticker.upper() in requested]
        else:
            result = [ticker.upper() for ticker in requested]
    else:
        result = universe

    if limit is not None:
        result = result[:limit]
    return result


def fetch_dividend_data(tickers=None, limit=None, sources=None, start_date=None, end_date=None):
    chosen_sources = set(sources or ["sec", "openbb"])
    sec_ticker_map = get_sec_ticker_map() if "sec" in chosen_sources else {}
    target_tickers = get_target_tickers(
        limit=limit,
        tickers=tickers,
        ticker_map=sec_ticker_map if sec_ticker_map and not tickers else None,
    )

    records = []
    for ticker in target_tickers:
        if "sec" in chosen_sources:
            cik = sec_ticker_map.get(ticker.upper())
            if cik is not None:
                sec_rows = extract_sec_dividend_data(cik)
                records.extend(normalize_sec_dividend_rows(ticker, sec_rows))

        if "openbb" in chosen_sources:
            if openbb_dividends is None:
                continue
            openbb_start = start_date or "2000-01-01"
            openbb_end = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                frame = openbb_dividends(ticker, openbb_start, openbb_end)
                records.extend(normalize_openbb_dividend_rows(ticker, frame))
            except Exception as exc:
                print(f"OpenBB fetch failed for {ticker}: {exc}")

    return merge_dividend_records(records)


def load_security_ids(conn):
    """Load active ticker and CIK mappings once for the entire database write."""
    rows = conn.execute(text("""
        SELECT DISTINCT ON (s.ticker) s.ticker, s.security_id, s.cik
        FROM reference.securities s
        WHERE s.active = TRUE
        ORDER BY s.ticker, s.updated_at DESC NULLS LAST, s.security_id
    """)).mappings()
    by_ticker = {}
    by_cik = {}
    for row in rows:
        by_ticker[row["ticker"].upper()] = row["security_id"]
        if row["cik"]:
            by_cik[str(row["cik"]).zfill(10)] = row["security_id"]
    return by_ticker, by_cik


def get_latest_dividend_rate(conn, security_id):
    """Return the most recent positive dividend amount for a security."""
    return conn.execute(text("""
        SELECT amount
        FROM raw.dividend_data
        WHERE security_id = :security_id AND amount > 0
        ORDER BY ex_dividend_date DESC NULLS LAST, payment_date DESC NULLS LAST
        LIMIT 1
    """), {"security_id": security_id}).scalar()


SERIES_RE = re.compile(r"\bSeries\b.*", re.IGNORECASE | re.DOTALL)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
CALL_DATE_RE = re.compile(
    r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})|(\d{2,4})-(\d{1,2})-(\d{1,2})"
)
LIQUIDATION_RE = re.compile(
    r"(?:liquidation\s+(?:preference|value)|par\s+value)"
    r"(?:\s+of)?\s*\$?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
FIXED_TO_FLOATING_RE = re.compile(r"fixed[- ]to[- ]floating|\bfixed/floating\b", re.IGNORECASE)
COUPON_FLOATING_RE = re.compile(r"\bfloating\b|\bfloat(?:ing)? rate\b|\bvariable\b|\badjustable\b", re.IGNORECASE)
FLOATING_SPREAD_RE = re.compile(
    r"(?:\+|plus)\s*([\d,]+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
FIXED_PERIOD_END_RE = re.compile(
    r"(?:initial|fixed)[^\n]*?(?:period\s+)?(?:ending|expir(?:ies|ing)|through|until)\s+"
    r"((?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|(?:\d{4}-\d{1,2}-\d{1,2}))",
    re.IGNORECASE,
)
TAX_EXEMPT_RE = re.compile(r"tax[- ]exempt|tax[- ]advantaged|qualified municipal", re.IGNORECASE)
NON_QUALIFIED_RE = re.compile(r"non[- ]qualified", re.IGNORECASE)
QUALIFIED_RE = re.compile(r"\bqualified\b(?!\s+municipal)", re.IGNORECASE)


def parse_percent(text):
    """Extract the first percentage (e.g. ``8.625%``) from a string."""
    if not text:
        return None
    m = PERCENT_RE.search(str(text))
    return safe_float(m.group(1)) if m else None


def parse_call_date(text):
    """Best-effort extraction of a call/redemption date from security text."""
    if not text:
        return None
    m = CALL_DATE_RE.search(str(text))
    if not m:
        return None
    try:
        return parse_date(m.group(0))
    except (TypeError, ValueError):
        return None


def parse_liquidation_preference(text):
    """Extract a liquidation preference / par value, e.g. ``par value $25``."""
    if not text:
        return None
    m = LIQUIDATION_RE.search(str(text))
    return safe_float(m.group(1)) if m else None


def parse_coupon_type(text, coupon_rate=None):
    """Classify the coupon as ``fixed``, ``floating``, or ``fixed-to-floating``.

    Keyword detection wins; otherwise a numeric coupon implies a fixed rate.
    """
    if not text:
        return None
    s = str(text)
    if FIXED_TO_FLOATING_RE.search(s):
        return "fixed-to-floating"
    if COUPON_FLOATING_RE.search(s):
        return "floating"
    if coupon_rate is not None:
        return "fixed"
    return None


def parse_fixed_period_end(text):
    """Best-effort extraction of the end of the fixed-rate period."""
    if not text:
        return None
    m = FIXED_PERIOD_END_RE.search(str(text))
    if not m:
        return None
    try:
        return parse_date(m.group(1))
    except (TypeError, ValueError):
        return None


def parse_floating_spread(text):
    """Extract the floating-rate spread, e.g. ``...Term SOFR + 5.375%``."""
    if not text:
        return None
    m = FLOATING_SPREAD_RE.search(str(text))
    return safe_float(m.group(1)) if m else None


def parse_tax_status(text):
    """Best-effort classification of dividend tax treatment."""
    if not text:
        return None
    s = str(text)
    if TAX_EXEMPT_RE.search(s):
        return "tax-exempt"
    if NON_QUALIFIED_RE.search(s):
        return "non-qualified"
    if QUALIFIED_RE.search(s):
        return "qualified"
    return None


def extract_security_series(security_name):
    """Extract the security series label from a security name.

    For example, ``ACRES Commercial Realty Corp. Series C Preferred Stock
    (8.625% Fixed-to-Floating)`` becomes ``Series C Preferred Stock
    (8.625% Fixed-to-Floating)``.
    """
    if not security_name:
        return None
    name = str(security_name)
    if re.search(r"\bpreferred\b", name, re.IGNORECASE):
        m = SERIES_RE.search(name)
        if m:
            return m.group(0).strip()
    return name.strip()


def fetch_ticker_profile(ticker, security_name=None, security_type=None):
    """Fetch and normalize a ticker profile summary for one dividend payer.

    Combines Yahoo Finance / OpenBB (yfinance provider) company profile and
    quote data with preferred-stock terms parsed from the security name.
    """
    data = openbb_stock_summary(ticker) if openbb_stock_summary is not None else {}
    text_source = " ".join(
        part for part in (security_name, data.get("short_name"), data.get("long_name"))
        if part
    )

    coupon_rate = parse_percent(security_name) or parse_percent(data.get("short_name"))

    return {
        "ticker": ticker,
        "provider": PROFILE_PROVIDER,
        "sector": data.get("sector"),
        "industry": data.get("industry") or data.get("industry_category"),
        "security_type": extract_security_series(security_name)
        or (security_type if security_type and security_type != "other" else None),
        "coupon_type": parse_coupon_type(text_source, coupon_rate=coupon_rate),
        "coupon_rate": coupon_rate,
        "fixed_period_end": parse_fixed_period_end(text_source),
        "floating_spread": parse_floating_spread(text_source),
        "tax_status": parse_tax_status(text_source),
        "call_date": parse_call_date(security_name),
        "liquidation_preference": parse_liquidation_preference(security_name),
        "raw_payload": json.dumps(data, default=str),
    }


def get_dividend_paying_securities(conn, limit=None, tickers=None):
    """Return active dividend-flagged securities to profile.

    The base list comes from ``raw.company_ticker`` (the SEC ticker universe
    refreshed by ``populate_raw_tables``). A ticker is eligible when its
    reference row is dividend-flagged or it has positive normalized dividend
    evidence, which preserves profiles when SEC Company Facts is unavailable.
    """
    params = {}
    filters = [
        "s.active = TRUE",
        "(s.dividend = TRUE OR EXISTS ("
        "SELECT 1 FROM raw.dividend_data d "
        "WHERE d.security_id = s.security_id AND d.amount > 0))",
    ]
    if tickers:
        filters.append("UPPER(ct.ticker) = ANY(:tickers)")
        params["tickers"] = [t.upper() for t in tickers]
    where = " AND ".join(filters)
    limit_sql = " LIMIT :limit" if limit else ""
    if limit is not None:
        params["limit"] = limit
    return conn.execute(text(f"""
        SELECT DISTINCT ON (ct.ticker)
               s.security_id, ct.ticker AS ticker, s.security_name, s.security_type
        FROM raw.company_ticker ct
        JOIN reference.securities s
          ON UPPER(s.ticker) = UPPER(ct.ticker)
        WHERE {where}
        ORDER BY ct.ticker, s.updated_at DESC NULLS LAST, s.security_id
        {limit_sql}
    """), params).mappings().all()


def populate_ticker_profiles(conn, limit=None, tickers=None):
    """Fetch and store a ticker profile summary for every dividend payer.

    The target list is read from ``raw.company_ticker`` intersected with the
    ``dividend = TRUE`` securities universe, so profiles are only fetched for
    tickers that issued a dividend. Writes one row per security to
    ``raw.ticker_profile`` (upserted on ``security_id``) so re-runs refresh
    the summary with current values.
    """
    candidates = get_dividend_paying_securities(conn, limit=limit, tickers=tickers)

    inserted = skipped = errors = 0
    for candidate in candidates:
        try:
            summary = fetch_ticker_profile(
                candidate["ticker"],
                security_name=candidate["security_name"],
                security_type=candidate["security_type"],
            )
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
            """), {**candidate, **summary})
            conn.execute(text("""
                UPDATE reference.securities
                SET coupon_rate = COALESCE(:coupon_rate, coupon_rate),
                    liquidation_preference = COALESCE(
                        :liquidation_preference, liquidation_preference
                    ),
                    call_date = COALESCE(:call_date, call_date),
                    updated_at = now()
                WHERE security_id = :security_id
            """), {**candidate, **summary})
            inserted += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"  Error populating profile for {candidate['ticker']}: {exc}")

    print("\n✓ Populated raw.ticker_profile:")
    print(f"  Candidates: {len(candidates)}")
    print(f"  Inserted/refreshed: {inserted}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
    return inserted


def _populate_preferred_terms(conn, limit=None):
    """Populate baseline preferred.security_terms from dividend-identified tickers.

    Runs after raw.dividend_data is written. Only fills gaps: existing rows
    (for example manual profiles with ``reviewed_by = 'manual_research'``) are
    left untouched via ``ON CONFLICT DO NOTHING``.
    """
    limit_sql = " LIMIT :limit" if limit else ""
    params = {"limit": limit} if limit else {}
    candidates = conn.execute(text(f"""
        SELECT DISTINCT s.security_id, s.ticker, s.security_name
        FROM reference.securities s
        JOIN raw.dividend_data d ON d.security_id = s.security_id
                WHERE s.active = TRUE
                    AND s.security_type = 'preferred stock'
                    AND (s.dividend = TRUE OR EXISTS (
                            SELECT 1 FROM raw.dividend_data d
                            WHERE d.security_id = s.security_id AND d.amount > 0
                    ))
        ORDER BY s.ticker
        {limit_sql}
    """), params).mappings().all()

    inserted = existing = errors = 0
    for candidate in candidates:
        try:
            series = (candidate["security_name"] or "")[:127]
            dividend_rate = get_latest_dividend_rate(conn, candidate["security_id"])
            result = conn.execute(text("""
                INSERT INTO preferred.security_terms
                    (security_id, preferred_series, dividend_rate,
                     confidence_score, reviewed_by, reviewed_at)
                VALUES (:security_id, :series, :dividend_rate, 0.3,
                        'auto_dividend_screen', now())
                ON CONFLICT (security_id) DO NOTHING
            """), {
                "security_id": candidate["security_id"],
                "series": series,
                "dividend_rate": dividend_rate,
            })
            if result.rowcount:
                inserted += 1
            else:
                existing += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"  Error populating preferred terms for {candidate['ticker']}: {exc}")

    print("\n✓ Populated preferred.security_terms:")
    print(f"  Candidates: {len(candidates)}")
    print(f"  Inserted: {inserted}")
    print(f"  Existing (kept): {existing}")
    print(f"  Errors: {errors}")
    return inserted


populate_preferred_terms = _populate_preferred_terms


def populate_dividend_data(limit=None, tickers=None, sources=None, start_date=None, end_date=None, populate_preferred_terms=True, populate_profiles=True, include_non_dividend=False):
    """Populate raw.dividend_data and raw.ticker_profile with normalized dividends and stock summaries."""
    normalized_sources = set((sources or ["sec", "openbb"]))
    print(f"Fetching dividend data from: {', '.join(sorted(normalized_sources))}")

    with engine.connect() as conn:
        dividend_tickers = get_target_dividend_tickers(
            conn,
            tickers=tickers,
            dividend_only=not include_non_dividend,
            limit=limit,
        )
    if include_non_dividend is False and not dividend_tickers:
        print("No dividend-flagged securities found. Run populate_raw_tables and populate_reference_tables first.")
        return 0

    dividend_data = fetch_dividend_data(
        tickers=dividend_tickers,
        limit=None,
        sources=normalized_sources,
        start_date=start_date,
        end_date=end_date,
    )
    print(f"Fetched {len(dividend_data)} normalized dividend records")

    if not dividend_data:
        print("No dividend data found. Exiting.")
        return 0

    inserted = 0
    skipped = 0
    errors = 0

    with engine.begin() as conn:
        ticker_security_ids, cik_security_ids = load_security_ids(conn)
        insert_rows = []
        for div in dividend_data:
            ticker = (div.get("ticker") or "").upper()
            security_id = ticker_security_ids.get(ticker)
            if security_id is None and div.get("cik") is not None:
                security_id = cik_security_ids.get(str(div["cik"]).zfill(10))

            ex_div_date = div.get("ex_dividend_date")
            if not security_id or not ex_div_date:
                skipped += 1
                if skipped <= 5 and not security_id:
                    print(f"  Warning: No security found for ticker {ticker or 'unknown'}")
                continue

            insert_rows.append({
                "sec_id": security_id,
                "ex_date": ex_div_date,
                "decl_date": div.get("declaration_date"),
                "rec_date": div.get("record_date"),
                "pay_date": div.get("payment_date"),
                "amount": float(div.get("amount", 0)),
                "adjusted_amount": div.get("adjusted_amount"),
                "frequency": div.get("frequency", "Annual"),
                "currency": div.get("currency", "USD"),
                "provider": div.get("provider", "SEC_XBRL"),
                "retrieved_at": datetime.now(timezone.utc),
            })

        if insert_rows:
            conn.execute(text("""
                INSERT INTO raw.dividend_data
                (security_id, ex_dividend_date, declaration_date, record_date,
                 payment_date, amount, adjusted_amount, frequency, currency, provider, retrieved_at)
                VALUES (:sec_id, :ex_date, :decl_date, :rec_date, :pay_date,
                        :amount, :adjusted_amount, :frequency, :currency, :provider, :retrieved_at)
                ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET
                    declaration_date = EXCLUDED.declaration_date,
                    record_date = EXCLUDED.record_date,
                    payment_date = EXCLUDED.payment_date,
                    amount = EXCLUDED.amount,
                    adjusted_amount = EXCLUDED.adjusted_amount,
                    frequency = EXCLUDED.frequency,
                    currency = EXCLUDED.currency,
                    retrieved_at = EXCLUDED.retrieved_at
            """), insert_rows)
            inserted = len(insert_rows)

    print("\n✓ Populated raw.dividend_data:")
    print(f"  Inserted: {inserted} records")
    print(f"  Skipped: {skipped} records")
    print(f"  Errors: {errors} records")

    if populate_preferred_terms:
        with engine.begin() as conn:
            _populate_preferred_terms(conn, limit=limit)

    if populate_profiles:
        with engine.begin() as conn:
            populate_ticker_profiles(conn, limit=limit, tickers=tickers)

    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N companies for testing")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers, e.g. 'AAPL,MSFT,JNJ'")
    parser.add_argument("--sources", type=str, default="all", choices=["all", "sec", "openbb"], help="Data source(s) to use")
    parser.add_argument("--start-date", type=str, default="2000-01-01", help="OpenBB start date")
    parser.add_argument("--end-date", type=str, default=None, help="OpenBB end date")
    parser.add_argument("--skip-preferred-terms", action="store_true",
                        help="Do not populate preferred.security_terms after loading dividends")
    parser.add_argument("--skip-profiles", action="store_true",
                        help="Do not fetch/store raw.ticker_profile summaries for dividend payers")
    parser.add_argument("--include-non-dividend", action="store_true",
                        help="Also fetch dividend events for securities not flagged as dividend payers")

    args = parser.parse_args()

    tickers_list = None
    if args.tickers:
        tickers_list = [t.strip().upper() for t in args.tickers.split(",") if t and t.strip()]

    selected_sources = ["sec", "openbb"] if args.sources == "all" else [args.sources]

    try:
        populate_dividend_data(
            limit=args.limit,
            tickers=tickers_list,
            sources=selected_sources,
            start_date=args.start_date,
            end_date=args.end_date,
            populate_preferred_terms=not args.skip_preferred_terms,
            populate_profiles=not args.skip_profiles,
            include_non_dividend=args.include_non_dividend,
        )
        print("\nDividend data population complete!")
        return 0
    except Exception as exc:
        print(f"\n✗ Error populating dividend data: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
