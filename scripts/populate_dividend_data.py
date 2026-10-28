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
        Earliest dividend date for the OpenBB source (the SEC XBRL source
        always returns full history regardless of this bound). Defaults to
        settings.dividend_lookback_start (12-month lookback; env
        DIVIDEND_LOOKBACK_START) so nightly runs acquire the 2025-01-01+
        window once and keep accruing.
    --end-date YYYY-MM-DD
        Latest dividend date (OpenBB); default open-ended, so announced
        upcoming ex-dates are kept.
    --full-history
        Total-historical provision for post-PoC: ignore the lookback bound and
        ask OpenBB for the full available history (from 1970-01-01). SEC XBRL
        already returns full history, so this only affects the OpenBB source.
    --skip-preferred-terms Do not populate preferred.security_terms after loading dividends
    --skip-profiles        Do not fetch/store raw.ticker_profile summaries for dividend payers
    --include-non-dividend Also fetch dividend events for securities not flagged dividend=TRUE
                           (default: restricted to the reference.securities dividend universe)

Examples:
    python -m scripts.populate_dividend_data --sources all --tickers AAPL,MSFT,JNJ
    python -m scripts.populate_dividend_data --limit 10 --sources sec
    python -m scripts.populate_dividend_data --sources openbb --tickers ACR-PC,ACR-PD
    # Post-PoC total-history backfill (one-time provision):
    python -m scripts.populate_dividend_data --sources openbb --full-history
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.populate_companyfacts import upsert_companyfacts
from src.crispdm.config import settings
from src.crispdm.db import engine
from src.crispdm.doc_clauses import depositary_ratio
from src.crispdm.sec_client import (
    build_companyfacts_concept_groups,
    get_company_tickers,
    get_companyfacts,
)
from src.crispdm.stage import stage_exit_code
from src.crispdm.ticker_profile_store import (
    NAME_PARSE_COLUMNS,
    OPENBB_COLUMNS,
    envelope_payload,
    upsert_ticker_profile,
)

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
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%B %d, %Y",
            "%B %d %Y",
            "%b %d, %Y",
            "%b %d %Y",
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value):
    """Map a provider currency label to a bare ISO-4217 alphabetic code.

    SEC XBRL keys units as ``USD/shares`` or ``CAD/per-shares`` and providers
    occasionally return a decorated label; only the alphabetic prefix is the
    currency. Anything that is not a plain three-letter code falls back to USD
    so the value always fits raw.dividend_data.currency (VARCHAR(8)) and
    satisfies the ``^[A-Z]{3}$`` check on reference.securities.currency.
    """
    code = str(value or "").strip().upper().split("/", 1)[0].strip()
    return code if CURRENCY_RE.match(code) else "USD"


FULL_HISTORY_START = "1970-01-01"
#: Feed recorded for an OPENBB frame that does not say which provider answered.
DEFAULT_OPENBB_FEED = "yfinance"
#: Days before a new OpenBB feed's first event in which the old feed's rows are
#: still treated as the same payments dated differently.
SUPERSEDE_TOLERANCE_DAYS = 7
#: An upcoming ex-date further out than this is kept only when it carries a
#: declaration date. FMP also lists scheduled coupons of exchange-traded notes out to
#: maturity (GECCG through 2029) -- projections, not announced dividends.
UNDECLARED_HORIZON_DAYS = 120


def _is_projection(ex_date, declaration_date, today=None):
    """True for an undeclared ex-date beyond the announcement horizon."""
    if ex_date is None or declaration_date is not None:
        return False
    today = today or date.today()
    return (ex_date - today).days > UNDECLARED_HORIZON_DAYS


SEC_DIVIDEND_CONCEPTS = (
    "CommonStockDividendsPerShareDeclared",
    "CommonStockDividendsPerShareCashPaid",
    "PreferredStockDividendsPerShareDeclared",
)

#: XBRL has no ex-date fact, so fact.end (the period end) is used as the proxy
#: for ex_dividend_date. That proxy is only as good as the filer's tag, and the
#: real filings contain typos: MTEX tags a period ending 2108-11-14. Aggregate
#: dollar concepts and dates outside this window are refused rather than stored
#: as if they were dividend history.
MAX_DIVIDEND_HORIZON_YEARS = 2
MIN_DIVIDEND_YEAR = 1970

#: Filers occasionally tag a per-share concept with the period's aggregate
#: dollars (HIG files 1,125,000,000 as PreferredStockDividendsPerShareDeclared;
#: ARR-PC files 306,800,000 as CommonStockDividendsPerShareCashPaid). The stored
#: median is 0.48 and the 99th percentile is 80, so no real per-share dividend
#: approaches this; anything larger is a unit error and is refused.
MAX_PER_SHARE_DIVIDEND = 1000.0


def plausible_dividend_date(value, today=None):
    """Return a dividend date that is a plausible ex-date, else None.

    Guards the ``fact.end`` proxy in two directions: far-future period ends
    (filer typos, or a units/century error) would otherwise be summed into
    every later trailing-dividend window and poison the feature forever,
    since the window is a ``RANGE`` that no future row ever leaves.
    """
    parsed = parse_date(value)
    if parsed is None:
        return None
    today = today or date.today()
    if parsed.year < MIN_DIVIDEND_YEAR:
        return None
    if parsed > today.replace(year=today.year + MAX_DIVIDEND_HORIZON_YEARS):
        return None
    return parsed


def _companyfacts_for_dividends(cik, conn):
    """Reuse a stored companyfacts payload or fetch + cache it (one row per CIK).

    The raw.companyfacts row is keyed by issuer CIK and shared by every listed
    security of the issuer. Caching here means the later companyfacts stage
    (scripts.populate_companyfacts) reuses this payload instead of downloading
    the same SEC JSON a second time.
    """
    cik = str(int(cik)).zfill(10)
    stored = conn.execute(
        text("SELECT raw_payload FROM raw.companyfacts WHERE cik = :cik"), {"cik": cik}
    ).scalar()
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
                    end = plausible_dividend_date(record.get("end"))
                    if end is None:
                        continue
                    rows.append(
                        {
                            "cik": str(int(cik)).zfill(10),
                            "concept": concept_name,
                            "ex_dividend_date": end,
                            "declaration_date": None,
                            "record_date": None,
                            "payment_date": end,
                            "amount": amount,
                            "frequency": "Annual",
                            "currency": normalize_currency(unit_type),
                            "filed_date": record.get("filed"),
                            "form": record.get("form", ""),
                            "accn": record.get("accn", ""),
                        }
                    )
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
        # An aggregate-dollar fact in the same units column as a per-share
        # amount is how BAC ended up with 20bn of "dividends" per share, so a
        # row that is not a per-share concept is dropped here rather than
        # silently becoming a yield.
        concept = row.get("concept") or ""
        if "pershare" not in concept.replace("_", "").replace(" ", "").lower():
            continue
        ex_date = plausible_dividend_date(row.get("ex_dividend_date"))
        if ex_date is None:
            continue
        if amount > MAX_PER_SHARE_DIVIDEND:
            continue
        normalized.append(
            {
                "ticker": ticker,
                "provider": "SEC_XBRL",
                "cik": row.get("cik"),
                "concept": concept,
                "ex_dividend_date": ex_date,
                "declaration_date": parse_date(row.get("declaration_date")),
                "record_date": parse_date(row.get("record_date")),
                "payment_date": parse_date(row.get("payment_date")),
                "amount": amount,
                "adjusted_amount": safe_float(row.get("adjusted_amount")),
                "frequency": (row.get("frequency") or "Annual").strip() or "Annual",
                "currency": normalize_currency(row.get("currency")),
            }
        )
    return normalized


def _text(value):
    """Stripped text, or '' for None/NaN (pandas fills missing feed fields with NaN)."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def normalize_openbb_dividend_rows(ticker, data_frame):
    normalized = []
    if data_frame is None:
        return normalized

    feed = getattr(data_frame, "attrs", {}).get("feed") or DEFAULT_OPENBB_FEED
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

        ex_dividend_date = parse_date(
            row.get("ex_dividend_date") or row.get("date") or row.get("payment_date")
        )
        declaration_date = parse_date(row.get("declaration_date"))
        if isinstance(ex_dividend_date, datetime):
            ex_dividend_date = ex_dividend_date.date()
        if _is_projection(ex_dividend_date, declaration_date):
            continue

        normalized.append(
            {
                "ticker": ticker,
                "provider": "OPENBB",
                "feed": feed,
                "concept": "",
                "ex_dividend_date": ex_dividend_date,
                "declaration_date": declaration_date,
                "record_date": parse_date(row.get("record_date")),
                "payment_date": parse_date(row.get("payment_date") or row.get("date")),
                "amount": amount,
                "amount_feed": _text(row.get("amount_feed")) or feed,
                "adjusted_amount": (
                    safe_float(row.get("adjusted_amount"))
                    or safe_float(row.get("adj_amount"))
                    or safe_float(row.get("adjusted_dividend"))
                ),
                "frequency": _text(row.get("frequency")) or _text(row.get("period")) or "Annual",
                "currency": normalize_currency(row.get("currency")),
            }
        )

    return _collapse_duplicate_payments(normalized)


def _collapse_duplicate_payments(rows):
    """Keep one row per payment when a feed lists it under two ex-dates.

    FMP occasionally repeats a payment: same payment date, same amount (within 1%),
    same or missing declaration date, a second ex-date days later (CAT 10-19 and
    10-26 for the 11-19 payment; RYAAY's copy even falls after its record date).
    Payments that merely share a pay date with different amounts -- a special next to
    a regular dividend, Brazilian interest on capital -- are distinct and kept.
    Preference: a declared row, then one whose ex-date is not after its record date,
    then the earliest ex-date.
    """

    def rank(row):
        record, ex = row.get("record_date"), row.get("ex_dividend_date")
        impossible = record is not None and ex is not None and ex > record
        return (row.get("declaration_date") is None, impossible, ex or date.max)

    def same_payment(a, b):
        if a.get("payment_date") is None or a.get("payment_date") != b.get("payment_date"):
            return False
        da, db = a.get("declaration_date"), b.get("declaration_date")
        if da is not None and db is not None and da != db:
            return False
        return abs(a["amount"] - b["amount"]) <= 0.01 * max(a["amount"], b["amount"])

    kept = []
    for row in sorted(rows, key=rank):
        if not any(same_payment(row, other) for other in kept):
            kept.append(row)
    return sorted(kept, key=lambda r: r.get("ex_dividend_date") or date.min)


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


#: Median-interval cadence buckets, days between consecutive ex-dates, in
#: ascending limit order. A security's cadence is one label shared by all its
#: rows. ``Irregular`` covers fewer than two events and any median above the
#: ``Annual`` border. Kept in lockstep with the V0065 backfill (PostgreSQL
#: ``percentile_cont(0.5)`` with the same borders). The cadence is
#: informational only: the feature build must not key on this column.
FREQUENCY_BUCKETS = (("Monthly", 35), ("Quarterly", 95), ("Semi-annual", 200), ("Annual", 400))


def _median(gaps):
    ordered = sorted(gaps)
    if not ordered:
        return None
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def infer_frequency(gap_days):
    """Classify a payment cadence from the days between consecutive ex-dates.

    The median interval decides. Linear interpolation between the two middle
    gaps matches PostgreSQL ``percentile_cont(0.5)``, so this Python and the
    V0065 SQL backfill agree. Fewer than two gaps, or a median above the
    ``Annual`` border, is ``Irregular``.
    """
    gaps = [int(g) for g in gap_days if g is not None]
    mid = _median(gaps)
    if mid is None:
        return "Irregular"
    for label, limit in FREQUENCY_BUCKETS:
        if mid <= limit:
            return label
    return "Irregular"


def cadence_from_events(fresh, stored):
    """Map each security to its payment-cadence label.

    ``fresh`` and ``stored`` are (security_id, provider, ex_date) event rows.
    The OPENBB series carries the true ex-dates and wins when it holds at
    least two events; the SEC series (fiscal period-end proxies) is the
    fallback. A security with fewer than two events in either series reads
    ``Irregular``.
    """
    merged = {}
    for security_id, provider, ex_date in [*fresh, *stored]:
        merged.setdefault(security_id, {}).setdefault(provider, set()).add(ex_date)
    out = {}
    for security_id, by_provider in merged.items():
        chosen = None
        for provider in ("OPENBB", "SEC_XBRL"):
            dates = sorted(by_provider.get(provider) or [])
            if len(dates) >= 2:
                chosen = dates
                break
        if chosen is None:
            out[security_id] = "Irregular"
            continue
        gaps = [(later - earlier).days for earlier, later in zip(chosen, chosen[1:])]
        out[security_id] = infer_frequency(gaps)
    return out


def _cadence_by_security(conn, pending):
    """Load stored ex-dates for the affected securities and combine with fresh.

    Computed over the stored plus incoming series, not the incoming window
    alone, so a true-annual payer is not relabelled ``Irregular`` by a
    12-month nightly lookback that only ever sees one of its payments.
    """
    if not pending:
        return {}
    security_ids = sorted({security_id for security_id, _, _ in pending})
    stored = conn.execute(
        text(
            "SELECT security_id, provider, ex_dividend_date FROM raw.dividend_data "
            "WHERE security_id = ANY(:security_ids)"
        ),
        {"security_ids": security_ids},
    ).all()
    return cadence_from_events(pending, stored)


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


def get_sec_ticker_map(include_historical=False):
    """Load the SEC ticker file once and return normalized ticker-to-CIK values.

    ``include_historical`` adds the recovered delisted tickers from
    reference.securities, which the current SEC file no longer lists.
    """
    mapping = {
        (entry.get("ticker") or "").strip().upper(): entry.get("cik_str")
        for entry in get_company_tickers().values()
        if entry.get("ticker") and entry.get("cik_str") is not None
    }
    if include_historical:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT ticker, cik FROM reference.securities "
                    "WHERE historical = TRUE AND cik IS NOT NULL"
                )
            ).all()
        for ticker, cik in rows:
            mapping.setdefault(str(ticker).strip().upper(), str(cik).zfill(10))
    return mapping


def get_target_dividend_tickers(
    conn,
    tickers=None,
    dividend_only=True,
    limit=None,
    include_historical=False,
    historical_only=False,
):
    """Resolve the dividend universe to fetch dividend events for.

    Returns active reference-securities tickers. By default only
    ``dividend = TRUE`` securities are returned so SEC XBRL and OpenBB requests
    are never made for tickers that do not pay a dividend. Explicit ``tickers``
    are intersected with the universe (unless ``dividend_only`` is False).
    """
    filters = (
        ["(s.active = TRUE OR s.historical = TRUE)"] if include_historical else ["s.active = TRUE"]
    )
    params = {}
    if dividend_only:
        filters.append("s.dividend = TRUE")
    where = " AND ".join(filters)
    rows = (
        conn.execute(
            text(f"""
        SELECT DISTINCT ON (s.ticker) s.ticker
        FROM reference.securities s
        WHERE {where}
        ORDER BY s.ticker, s.updated_at DESC NULLS LAST
    """),
            params,
        )
        .mappings()
        .all()
    )
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


def fetch_dividend_data(
    tickers=None,
    limit=None,
    sources=None,
    start_date=None,
    end_date=None,
    full_history=False,
    include_historical=False,
):
    chosen_sources = set(sources or ["sec", "openbb"])
    sec_ticker_map = (
        get_sec_ticker_map(include_historical=include_historical) if "sec" in chosen_sources else {}
    )
    target_tickers = get_target_tickers(
        limit=limit,
        tickers=tickers,
        ticker_map=sec_ticker_map if sec_ticker_map and not tickers else None,
    )

    records = []
    amount_checks = _load_amount_checks() if "openbb" in chosen_sources else {}
    new_checks = []
    for ticker in target_tickers:
        if "sec" in chosen_sources:
            cik = sec_ticker_map.get(ticker.upper())
            if cik is not None:
                sec_rows = extract_sec_dividend_data(cik)
                records.extend(normalize_sec_dividend_rows(ticker, sec_rows))

        if "openbb" in chosen_sources:
            if openbb_dividends is None:
                continue
            if full_history:
                openbb_start = FULL_HISTORY_START
            else:
                openbb_start = start_date or settings.dividend_lookback_start.isoformat()
            # No default end date: FMP publishes declared ex-dates that are still ahead,
            # and capping at today would drop the announced next dividend.
            try:
                frame = openbb_dividends(
                    ticker,
                    openbb_start,
                    end_date,
                    amount_checks=amount_checks.get(ticker.upper(), {}),
                )
                records.extend(normalize_openbb_dividend_rows(ticker, frame))
                for check in getattr(frame, "attrs", {}).get("amount_checks") or []:
                    new_checks.append({"ticker": ticker.upper(), **check})
            except Exception as exc:
                print(f"OpenBB fetch failed for {ticker}: {exc}")

    _save_amount_checks(new_checks)
    return merge_dividend_records(records)


#: An unresolved FMP/Yahoo disagreement is asked of Polygon again after this long.
RECHECK_UNRESOLVED_DAYS = 7


def _load_amount_checks():
    """Earlier FMP/Yahoo amount verdicts as {ticker: {ex_date: row}}.

    Unresolved verdicts are checked again after ``RECHECK_UNRESOLVED_DAYS`` only when
    Polygon gave no figure or a USD one; a local-currency-only figure (FORFF in CAD,
    ASRMF in MXN) will not change, and FMP's USD conversion stays. A database
    without the V0083 table just has no cache.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                SELECT ticker, ex_dividend_date, fmp_amount, yahoo_amount, chosen
                FROM raw.dividend_amount_check
                WHERE chosen <> 'unresolved'
                   OR checked_at > now() - make_interval(days => :days)
                   OR COALESCE(polygon_currency, 'USD') NOT IN ('USD', '')
            """),
                {"days": RECHECK_UNRESOLVED_DAYS},
            ).mappings()
            checks = {}
            for row in rows:
                checks.setdefault(row["ticker"], {})[row["ex_dividend_date"]] = dict(row)
            return checks
    except Exception as exc:  # noqa: BLE001 - the cache is an optimisation
        print(f"Dividend amount verdict cache unavailable: {exc}")
        return {}


def _save_amount_checks(checks):
    if not checks:
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO raw.dividend_amount_check
                (ticker, ex_dividend_date, fmp_amount, yahoo_amount, polygon_amount,
                 polygon_currency, chosen, checked_at)
                VALUES (:ticker, :ex_dividend_date, :fmp_amount, :yahoo_amount,
                        :polygon_amount, :polygon_currency, :chosen, now())
                ON CONFLICT (ticker, ex_dividend_date) DO UPDATE SET
                    fmp_amount = EXCLUDED.fmp_amount,
                    yahoo_amount = EXCLUDED.yahoo_amount,
                    polygon_amount = EXCLUDED.polygon_amount,
                    polygon_currency = EXCLUDED.polygon_currency,
                    chosen = EXCLUDED.chosen,
                    checked_at = EXCLUDED.checked_at
            """),
                checks,
            )
    except Exception as exc:  # noqa: BLE001 - verdicts are re-derived next run
        print(f"Could not store dividend amount verdicts: {exc}")
        return
    chosen = {}
    for check in checks:
        chosen[check["chosen"]] = chosen.get(check["chosen"], 0) + 1
    print(f"Settled FMP/Yahoo amount disagreements: {chosen}")


def load_security_ids(conn, include_historical=False, historical_only=False):
    """Load active ticker and CIK mappings once for the entire database write."""
    if historical_only:
        universe = "s.historical = TRUE"
    elif include_historical:
        universe = "(s.active = TRUE OR s.historical = TRUE)"
    else:
        universe = "s.active = TRUE"
    rows = conn.execute(
        text(f"""
        SELECT DISTINCT ON (s.ticker) s.ticker, s.security_id, s.cik
        FROM reference.securities s
        WHERE {universe}
        ORDER BY s.ticker, s.updated_at DESC NULLS LAST, s.security_id
    """)
    ).mappings()
    by_ticker = {}
    by_cik = {}
    for row in rows:
        by_ticker[row["ticker"].upper()] = row["security_id"]
        if row["cik"]:
            by_cik[str(row["cik"]).zfill(10)] = row["security_id"]
    return by_ticker, by_cik


def get_latest_dividend_rate(conn, security_id):
    """Return the most recent positive per-share dividend amount for a security.

    Class-aware, because a preferred series routinely carries its issuer's
    common-stock dividend facts: without the concept filter the "latest amount"
    for a preferred was usually the issuer's common dividend or an annual
    CashPaid aggregate. For a preferred security this accepts an OPENBB row (a
    true per-symbol event) or the per-share PreferredStockDividendsPerShareDeclared
    concept; the CashPaid aggregate is never a per-share amount and is excluded.
    Amounts above $1000 per share are refused as implausible (matches
    doc_clauses.MAX_PER_SHARE / the security-terms view guard).
    """
    return conn.execute(
        text("""
        SELECT d.amount
        FROM raw.dividend_data d
        JOIN reference.securities s ON s.security_id = d.security_id
        WHERE d.security_id = :security_id AND d.amount > 0
          AND COALESCE(d.concept, '') <> 'CommonStockDividendsPerShareCashPaid'
          AND d.amount <= 1000
          AND (
                s.security_type <> 'preferred stock'
                OR d.provider = 'OPENBB'
                OR d.concept = 'PreferredStockDividendsPerShareDeclared'
                OR COALESCE(d.concept, '') = ''
              )
        ORDER BY (d.provider = 'OPENBB') DESC,
                 d.ex_dividend_date DESC NULLS LAST,
                 d.payment_date DESC NULLS LAST
        LIMIT 1
    """),
        {"security_id": security_id},
    ).scalar()


SERIES_RE = re.compile(r"\bSeries\b.*", re.IGNORECASE | re.DOTALL)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
CALL_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})|(\d{2,4})-(\d{1,2})-(\d{1,2})")
LIQUIDATION_RE = re.compile(
    r"liquidation\s+(?:preference|value)(?:\s+of)?\s*\$?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
LIQUIDATION_TRAILING_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:per\s+share\s+)?liquidation\s+(?:preference|value)",
    re.IGNORECASE,
)
PAR_VALUE_RE = re.compile(r"par\s+value(?:\s+of)?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
#: A par value below this is a nominal legal par (``$0.01``, ``$0.0001``), not a
#: stated liquidation amount; matches ``doc_clauses.MIN_PER_SHARE``.
MIN_PAR_AS_LIQUIDATION = 1.0
FIXED_TO_FLOATING_RE = re.compile(r"fixed[- ]to[- ]floating|\bfixed/floating\b", re.IGNORECASE)
COUPON_FLOATING_RE = re.compile(
    r"\bfloating\b|\bfloat(?:ing)? rate\b|\bvariable\b|\badjustable\b", re.IGNORECASE
)
#: A spread over a reference rate: ``SOFR + 5.375%``, ``plus 4.15%``,
#: ``spread of 3.00%``. The ``+`` sign must sit against the number, so a hyphen
#: in ``Non-Cumulative`` or a series label cannot be mistaken for a spread.
FLOATING_SPREAD_RE = re.compile(
    r"(?:\+|plus|over|above|sofr|libor|spread(?:\s+of)?)\s*([\d,]+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
#: A date token inside a title: numeric (``2028-07-30``, ``7/30/2028``) or a
#: full month-name date (``October 30, 2028``). A month-and-year-only token
#: (``Apr 2028``) is deliberately excluded: it carries no day, and inventing one
#: would store a fabricated date.
_DATE_PATTERN = (
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
)
#: The end of a fixed-rate period, phrased ``initial/fixed ... ending|expires|
#: through|until|due <date>``. US fixed-to-floating titles rarely carry this, so
#: the field is usually NULL; the pattern exists for the titles that do.
FIXED_PERIOD_END_RE = re.compile(
    r"(?:initial|fixed)[^\n]*?(?:period\s+)?"
    r"(?:ending|expir(?:ies|ing)|through|until|due|redeemable(?:\s+on\s+or\s+after)?|"
    r"callable(?:\s+on\s+or\s+after)?)\s+"
    rf"({_DATE_PATTERN})",
    re.IGNORECASE,
)
TAX_EXEMPT_RE = re.compile(r"tax[- ]exempt|tax[- ]advantaged|qualified municipal", re.IGNORECASE)
NON_QUALIFIED_RE = re.compile(r"non[- ]qualified", re.IGNORECASE)
QUALIFIED_RE = re.compile(r"\bqualified\b(?!\s+municipal)", re.IGNORECASE)


MIXED_FRACTION_PERCENT_RE = re.compile(r"\b(\d+)\s+(\d)/(\d{1,2})\s*%")


def parse_percent(text):
    """Extract the first percentage (``8.625%``, or ``8 3/8%``) from a string."""
    if not text:
        return None
    m = PERCENT_RE.search(str(text))
    fraction = MIXED_FRACTION_PERCENT_RE.search(str(text))
    # "8 3/8%" would otherwise read as the "8%" ending the fraction.
    if fraction and (m is None or fraction.start() <= m.start()) and int(fraction.group(3)):
        whole, numerator, denominator = (int(part) for part in fraction.groups())
        return whole + numerator / denominator
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
    """Extract a per-share liquidation preference from a security title.

    An explicit ``liquidation preference $25`` / ``$25.00 liquidation
    preference`` wins. ``par value $25`` is accepted as the stated amount, but
    a nominal par such as ``par value $0.0001`` is not a liquidation preference.
    """
    if not text:
        return None
    s = str(text)
    for pattern in (LIQUIDATION_RE, LIQUIDATION_TRAILING_RE):
        m = pattern.search(s)
        if m:
            return safe_float(m.group(1))
    m = PAR_VALUE_RE.search(s)
    value = safe_float(m.group(1)) if m else None
    return value if value is not None and value >= MIN_PAR_AS_LIQUIDATION else None


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


def summarize_ticker_profile(ticker, security_name=None, security_type=None, data=None):
    """Normalize one ticker profile from a title and an OpenBB summary dict.

    Pure (no network) so the repair job re-derives the name-parse columns with
    exactly the logic the nightly writers use.
    """
    data = data or {}
    text_source = " ".join(
        part for part in (security_name, data.get("short_name"), data.get("long_name")) if part
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
        # A depositary title quotes the underlying share's par ("1/1,000th
        # interest in a share ... $1.00 par"), not the listed receipt's
        # preference; only the contract miner establishes that equivalent.
        "liquidation_preference": None
        if depositary_ratio(security_name)
        else parse_liquidation_preference(security_name),
        "raw_payload": json.dumps(data, default=str),
    }


def fetch_ticker_profile(ticker, security_name=None, security_type=None):
    """Fetch and normalize a ticker profile summary for one dividend payer.

    Combines Yahoo Finance / OpenBB (yfinance provider) company profile and
    quote data with preferred-stock terms parsed from the security name.
    """
    data = openbb_stock_summary(ticker) if openbb_stock_summary is not None else {}
    return summarize_ticker_profile(ticker, security_name, security_type, data)


def get_dividend_paying_securities(
    conn, limit=None, tickers=None, include_historical=False, historical_only=False
):
    """Return active dividend-flagged securities to profile.

    The base list comes from ``raw.company_ticker`` (the SEC ticker universe
    refreshed by ``populate_raw_tables``). A ticker is eligible when its
    reference row is dividend-flagged or it has positive normalized dividend
    evidence, which preserves profiles when SEC Company Facts is unavailable.
    """
    params = {}
    if historical_only:
        universe = "s.historical = TRUE"
    elif include_historical:
        universe = "(s.active = TRUE OR s.historical = TRUE)"
    else:
        universe = "s.active = TRUE"
    filters = [
        universe,
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
    return (
        conn.execute(
            text(f"""
        SELECT DISTINCT ON (ct.ticker)
               s.security_id, ct.ticker AS ticker, s.security_name, s.security_type
        FROM raw.company_ticker ct
        JOIN reference.securities s
          ON UPPER(s.ticker) = UPPER(ct.ticker)
        WHERE {where}
        ORDER BY ct.ticker, s.updated_at DESC NULLS LAST, s.security_id
        {limit_sql}
    """),
            params,
        )
        .mappings()
        .all()
    )


def populate_ticker_profiles(conn, limit=None, tickers=None):
    """Fetch and store a ticker profile summary for every dividend payer.

    The target list is read from ``raw.company_ticker`` intersected with the
    ``dividend = TRUE`` securities universe, so profiles are only fetched for
    tickers that issued a dividend. Writes one row per security to
    ``raw.ticker_profile`` (upserted on ``security_id``) so re-runs refresh
    the summary with current values.

    ``coupon_rate`` and the other per-series terms come only from the
    per-security name parse. Writes go through
    ``src.crispdm.ticker_profile_store``: the observation is appended to
    ``raw.ticker_profile_load`` and the name-parse columns are owned (a NULL
    parse clears a stale value); sector/industry are owned only when OpenBB
    returned a profile, so a failed fetch does not erase them.
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
            openbb = json.loads(summary.get("raw_payload") or "{}")
            row = {
                **candidate,
                **summary,
                "raw_payload": envelope_payload(openbb=openbb),
            }
            upsert_ticker_profile(
                conn,
                row,
                loader="populate_dividend_data",
                owned_columns=NAME_PARSE_COLUMNS + (OPENBB_COLUMNS if openbb else ()),
            )
            # Only a preferred series carries the terms this name parse recovers.
            # Without the security_type guard a common-stock ticker such as "BCO"
            # inherited the issuer's preferred coupon/liquidation from its name
            # (103 common rows were carrying a coupon). The liquidation value is
            # also range-guarded: a nominal par below $1 is not a stated
            # preference (matches doc_clauses.MIN_PER_SHARE and the view guard).
            conn.execute(
                text("""
                UPDATE reference.securities
                SET coupon_rate = COALESCE(:coupon_rate, coupon_rate),
                    liquidation_preference = COALESCE(
                        CASE WHEN :liquidation_preference BETWEEN 1 AND 1000
                             THEN :liquidation_preference END,
                        liquidation_preference
                    ),
                    call_date = COALESCE(:call_date, call_date),
                    updated_at = now()
                WHERE security_id = :security_id
                  AND security_type = 'preferred stock'
            """),
                {**candidate, **summary},
            )
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
    candidates = (
        conn.execute(
            text(f"""
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
    """),
            params,
        )
        .mappings()
        .all()
    )

    inserted = existing = errors = 0
    for candidate in candidates:
        try:
            series = (candidate["security_name"] or "")[:127]
            dividend_rate = get_latest_dividend_rate(conn, candidate["security_id"])
            result = conn.execute(
                text("""
                INSERT INTO preferred.security_terms
                    (security_id, preferred_series, dividend_rate,
                     confidence_score, reviewed_by, reviewed_at)
                VALUES (:security_id, :series, :dividend_rate, 0.3,
                        'auto_dividend_screen', now())
                ON CONFLICT (security_id) DO NOTHING
            """),
                {
                    "security_id": candidate["security_id"],
                    "series": series,
                    "dividend_rate": dividend_rate,
                },
            )
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


def _drop_superseded_feed_rows(conn, insert_rows, window_start, window_end=None):
    """Remove stored OPENBB rows that the incoming series no longer carries.

    One security keeps one listing-level series, and the feed that answered is
    authoritative over the range it covers: stored OPENBB rows there whose ex-date is
    not among the incoming ones are deleted (rows with the same ex-date are
    overwritten by the upsert). That removes
      * another feed's copy of the same payment dated differently -- GFIOF is two
        days apart between Yahoo and FMP on every event -- which would otherwise be
        counted twice by every trailing-dividend feature, and
      * this feed's own rows it has since corrected or dropped (an announced ex-date
        moved, a duplicate collapsed by ``_collapse_duplicate_payments``).
    The range starts at the incoming first event -- for another feed's rows
    ``SUPERSEDE_TOLERANCE_DAYS`` earlier, so its copy of that first payment is caught
    -- and never before ``window_start``; older history stays.
    """
    by_security = {}
    for row in insert_rows:
        if row["provider"] != "OPENBB" or not row.get("feed"):
            continue
        feeds, dates = by_security.setdefault(row["sec_id"], (set(), set()))
        feeds.add(row["feed"])
        dates.add(row["ex_date"])
    removed = 0
    for security_id, (feeds, dates) in by_security.items():
        if len(feeds) != 1:
            continue
        first = min(dates)
        first = first.date() if isinstance(first, datetime) else first
        lower = str(window_start)[:10]
        removed += conn.execute(
            text("""
            DELETE FROM raw.dividend_data
            WHERE security_id = :sid AND provider = 'OPENBB'
              AND ex_dividend_date >= CASE WHEN feed IS NOT DISTINCT FROM :feed
                                           THEN CAST(:same_start AS date)
                                           ELSE CAST(:other_start AS date) END
              AND (CAST(:end AS date) IS NULL OR ex_dividend_date <= CAST(:end AS date))
              AND NOT (ex_dividend_date = ANY(:dates))
            """),
            {
                "sid": security_id,
                "feed": next(iter(feeds)),
                "same_start": max(lower, first.isoformat()),
                "other_start": max(
                    lower, (first - timedelta(days=SUPERSEDE_TOLERANCE_DAYS)).isoformat()
                ),
                "end": window_end,
                "dates": sorted(dates),
            },
        ).rowcount
    return removed


def populate_dividend_data(
    limit=None,
    tickers=None,
    sources=None,
    start_date=None,
    end_date=None,
    full_history=False,
    populate_preferred_terms=True,
    populate_profiles=True,
    include_non_dividend=False,
    include_historical=False,
    historical_only=False,
):
    """Populate raw.dividend_data and raw.ticker_profile with normalized dividends and stock summaries."""
    normalized_sources = set((sources or ["sec", "openbb"]))
    print(f"Fetching dividend data from: {', '.join(sorted(normalized_sources))}")

    with engine.connect() as conn:
        dividend_tickers = get_target_dividend_tickers(
            conn,
            tickers=tickers,
            dividend_only=not include_non_dividend,
            limit=limit,
            include_historical=include_historical,
            historical_only=historical_only,
        )
    if include_non_dividend is False and not dividend_tickers:
        print(
            "No dividend-flagged securities found. Run populate_raw_tables and populate_reference_tables first."
        )
        return 0

    dividend_data = fetch_dividend_data(
        tickers=dividend_tickers,
        limit=None,
        sources=normalized_sources,
        start_date=start_date,
        end_date=end_date,
        full_history=full_history,
        include_historical=include_historical,
    )
    print(f"Fetched {len(dividend_data)} normalized dividend records")

    if not dividend_data:
        print("No dividend data found. Exiting.")
        return 0

    inserted = 0
    skipped = 0
    errors = 0
    replaced = 0
    if full_history:
        window_start = FULL_HISTORY_START
    else:
        window_start = start_date or settings.dividend_lookback_start.isoformat()

    with engine.begin() as conn:
        ticker_security_ids, cik_security_ids = load_security_ids(
            conn, include_historical=include_historical, historical_only=historical_only
        )
        pending = []
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

            provider = div.get("provider", "SEC_XBRL")
            pending.append((security_id, provider, ex_div_date))
            insert_rows.append(
                {
                    "sec_id": security_id,
                    "ex_date": ex_div_date,
                    "decl_date": div.get("declaration_date"),
                    "rec_date": div.get("record_date"),
                    "pay_date": div.get("payment_date"),
                    "amount": float(div.get("amount", 0)),
                    "adjusted_amount": div.get("adjusted_amount"),
                    "frequency": "Irregular",  # overwritten from the cadence pass below
                    "currency": normalize_currency(div.get("currency")),
                    "provider": provider,
                    "feed": div.get("feed") if provider == "OPENBB" else None,
                    "amount_feed": (
                        (div.get("amount_feed") or div.get("feed"))
                        if provider == "OPENBB"
                        else None
                    ),
                    "concept": (div.get("concept") or "")[:96],
                    "retrieved_at": datetime.now(timezone.utc),
                }
            )

        replaced = _drop_superseded_feed_rows(conn, insert_rows, window_start, end_date)

        # The cadence is a property of the security's payment series, not of a
        # single provider row: derive it once per security from the stored and
        # incoming ex-dates (OpenBB's true ex-dates first, SEC's period-end
        # proxies as the fallback) and stamp every row alike.
        frequencies = _cadence_by_security(conn, pending)
        for row, (security_id, _, _) in zip(insert_rows, pending):
            row["frequency"] = frequencies.get(security_id, "Irregular")

        if insert_rows:
            conn.execute(
                text("""
                INSERT INTO raw.dividend_data
                (security_id, ex_dividend_date, declaration_date, record_date,
                 payment_date, amount, adjusted_amount, frequency, currency, provider,
                 feed, amount_feed, concept, retrieved_at)
                VALUES (:sec_id, :ex_date, :decl_date, :rec_date, :pay_date,
                        :amount, :adjusted_amount, :frequency, :currency, :provider,
                        :feed, :amount_feed, :concept, :retrieved_at)
                ON CONFLICT (security_id, ex_dividend_date, provider) DO UPDATE SET
                    declaration_date = EXCLUDED.declaration_date,
                    record_date = EXCLUDED.record_date,
                    payment_date = EXCLUDED.payment_date,
                    amount = EXCLUDED.amount,
                    adjusted_amount = EXCLUDED.adjusted_amount,
                    frequency = EXCLUDED.frequency,
                    currency = EXCLUDED.currency,
                    feed = EXCLUDED.feed,
                    amount_feed = EXCLUDED.amount_feed,
                    concept = EXCLUDED.concept,
                    retrieved_at = EXCLUDED.retrieved_at
            """),
                insert_rows,
            )
            inserted = len(insert_rows)

    print("\n✓ Populated raw.dividend_data:")
    print(f"  Inserted: {inserted} records")
    print(f"  Replaced: {replaced} superseded rows from another OpenBB feed")
    print(f"  Skipped: {skipped} records")
    print(f"  Errors: {errors} records")

    if populate_preferred_terms:
        with engine.begin() as conn:
            _populate_preferred_terms(conn, limit=limit)

    if populate_profiles:
        with engine.begin() as conn:
            populate_ticker_profiles(conn, limit=limit, tickers=tickers)

    return inserted, skipped, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to first N companies for testing"
    )
    parser.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated tickers, e.g. 'AAPL,MSFT,JNJ'"
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="all",
        choices=["all", "sec", "openbb"],
        help="Data source(s) to use",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=settings.dividend_lookback_start.isoformat(),
        help="OpenBB start date (default: dividend_lookback_start from config/.env)",
    )
    parser.add_argument("--end-date", type=str, default=None, help="OpenBB end date")
    parser.add_argument(
        "--full-history",
        action="store_true",
        help="Post-PoC total-history provision: ask OpenBB for the full available "
        "history (from 1970-01-01) instead of the 12-month lookback",
    )
    parser.add_argument(
        "--skip-preferred-terms",
        action="store_true",
        help="Do not populate preferred.security_terms after loading dividends",
    )
    parser.add_argument(
        "--skip-profiles",
        action="store_true",
        help="Do not fetch/store raw.ticker_profile summaries for dividend payers",
    )
    parser.add_argument(
        "--include-non-dividend",
        action="store_true",
        help="Also fetch dividend events for securities not flagged as dividend payers",
    )
    parser.add_argument(
        "--include-historical",
        action="store_true",
        help="Also fetch dividend events for securities recovered from EDGAR after delisting",
    )
    parser.add_argument(
        "--historical-only",
        action="store_true",
        help="Fetch dividends only for the recovered delisted securities",
    )

    args = parser.parse_args()

    tickers_list = None
    if args.tickers:
        tickers_list = [t.strip().upper() for t in args.tickers.split(",") if t and t.strip()]

    selected_sources = ["sec", "openbb"] if args.sources == "all" else [args.sources]

    try:
        inserted, skipped, errors = populate_dividend_data(
            limit=args.limit,
            tickers=tickers_list,
            sources=selected_sources,
            start_date=args.start_date,
            end_date=args.end_date,
            full_history=args.full_history,
            populate_preferred_terms=not args.skip_preferred_terms,
            populate_profiles=not args.skip_profiles,
            include_non_dividend=args.include_non_dividend,
            include_historical=args.include_historical,
            historical_only=args.historical_only,
        )
        # A re-run that finds every dividend already stored inserts nothing and
        # skips everything, which is the stage working. Failing on that would
        # make the nightly unrunnable on the morning after a good one.
        code = stage_exit_code(
            "populate_dividend_data", inserted + errors, inserted, skipped=skipped, errors=errors
        )
        if code:
            return code
        print("\nDividend data population complete!")
        return 0
    except Exception as exc:
        print(f"\n✗ Error populating dividend data: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
