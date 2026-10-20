"""Populate raw.fmp_statements, raw.fmp_dcf and raw.fmp_filings from OpenBB FMP.

Supporting fundamental data for the investment-analysis worksheet: reported
income/balance/cash statements, FMP's own discounted-cash-flow estimate (read
directly, since OpenBB 4.7.2 exposes no DCF command), and FMP's company filings
as a second source alongside the direct SEC submissions.

Runs over the active dividend universe (the same gating set as the other
provider stages). A security's rows are committed as one unit so a re-run is
resumable; a security that fails is counted and the run continues.

Nothing here feeds the model: fundamentals.periodic_financials stays SEC XBRL
only and the feature build never reads these tables.

Usage:
    python -m scripts.populate_fmp_fundamentals
    python -m scripts.populate_fmp_fundamentals --tickers AAPL,MSFT
    python -m scripts.populate_fmp_fundamentals --limit 25 --statement-limit 3
    python -m scripts.populate_fmp_fundamentals --skip-dcf --skip-filings
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.config import settings
from src.crispdm.db import engine
from src.crispdm.openbb_client import (
    _has_fmp_key,
    discounted_cash_flow,
    filings,
    financial_statements,
)
from src.crispdm.stage import stage_exit_code

STATEMENT_TYPES = ("income", "balance", "cash")
DEFAULT_STATEMENT_LIMIT = 5


def load_securities(conn, tickers=None, limit=None):
    """Active dividend securities to gather, in a stable order."""
    clauses = ["s.active = TRUE", "s.dividend = TRUE"]
    params = {}
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    sql = f"""
        SELECT s.security_id, s.ticker
        FROM reference.securities s
        WHERE {" AND ".join(clauses)}
        ORDER BY s.security_id
    """
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit
    return conn.execute(text(sql), params).mappings().all()


def _statement_key(row):
    """(period_end, fiscal_period, fiscal_year, filing_date) or None when unkeyable."""
    period_end = pd.to_datetime(row.get("period_ending"), errors="coerce")
    filing_date = pd.to_datetime(row.get("filing_date"), errors="coerce")
    if pd.isna(period_end) or pd.isna(filing_date):
        return None
    try:
        fiscal_year = int(row.get("fiscal_year"))
    except (TypeError, ValueError):
        fiscal_year = None
    return (
        period_end.date(),
        str(row.get("fiscal_period") or ""),
        fiscal_year,
        filing_date.date(),
    )


def upsert_statement(conn, security_id, statement, row):
    """Upsert one FMP statement row; returns 1 when it was keyed, 0 when skipped."""
    key = _statement_key(row)
    if key is None:
        return 0
    period_end, fiscal_period, fiscal_year, filing_date = key
    metrics = json.dumps(row, sort_keys=True, default=str)
    conn.execute(
        text("""
        INSERT INTO raw.fmp_statements
            (security_id, statement, period_end, fiscal_period, fiscal_year,
             filing_date, reported_currency, metrics, content_hash, provider, retrieved_at)
        VALUES (:security_id, :statement, :period_end, :fiscal_period, :fiscal_year,
                :filing_date, :reported_currency, CAST(:metrics AS jsonb),
                :content_hash, 'FMP', now())
        ON CONFLICT (security_id, statement, period_end, fiscal_period, filing_date)
        DO UPDATE SET
            fiscal_year = EXCLUDED.fiscal_year,
            reported_currency = EXCLUDED.reported_currency,
            metrics = CASE
                WHEN raw.fmp_statements.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                THEN EXCLUDED.metrics ELSE raw.fmp_statements.metrics END,
            content_hash = EXCLUDED.content_hash,
            retrieved_at = now()
        """),
        {
            "security_id": security_id,
            "statement": statement,
            "period_end": period_end,
            "fiscal_period": fiscal_period,
            "fiscal_year": fiscal_year,
            "filing_date": filing_date,
            "reported_currency": row.get("reported_currency"),
            "metrics": metrics,
            "content_hash": hashlib.sha256(metrics.encode("utf-8")).hexdigest(),
        },
    )
    return 1


def upsert_dcf(conn, security_id, row):
    """Upsert one FMP DCF estimate; returns 1 when it was keyed, 0 when skipped."""
    as_of = row.get("as_of_date")
    if as_of is None:
        return 0
    conn.execute(
        text("""
        INSERT INTO raw.fmp_dcf
            (security_id, as_of_date, dcf, stock_price, reported_currency, provider,
             retrieved_at)
        VALUES (:security_id, :as_of_date, :dcf, :stock_price, :reported_currency,
                'FMP', now())
        ON CONFLICT (security_id, as_of_date) DO UPDATE SET
            dcf = EXCLUDED.dcf,
            stock_price = EXCLUDED.stock_price,
            reported_currency = EXCLUDED.reported_currency,
            retrieved_at = now()
        """),
        {
            "security_id": security_id,
            "as_of_date": as_of,
            "dcf": row.get("dcf"),
            "stock_price": row.get("stock_price"),
            "reported_currency": row.get("reported_currency"),
        },
    )
    return 1


def upsert_filings(conn, security_id, frame):
    """Upsert every FMP filing row; returns the number written."""
    if frame is None or frame.empty:
        return 0
    written = 0
    for row in frame.to_dict("records"):
        filing_date = pd.to_datetime(row.get("filing_date"), errors="coerce")
        report_type = row.get("report_type")
        report_url = row.get("report_url")
        if pd.isna(filing_date) or not report_type or not report_url:
            continue
        accepted = pd.to_datetime(row.get("accepted_date"), errors="coerce")
        conn.execute(
            text("""
            INSERT INTO raw.fmp_filings
                (security_id, filing_date, report_type, report_url, filing_url,
                 accepted_date, provider, retrieved_at)
            VALUES (:security_id, :filing_date, :report_type, :report_url, :filing_url,
                    :accepted_date, 'FMP', now())
            ON CONFLICT (security_id, filing_date, report_type, report_url) DO UPDATE SET
                filing_url = EXCLUDED.filing_url,
                accepted_date = EXCLUDED.accepted_date,
                retrieved_at = now()
            """),
            {
                "security_id": security_id,
                "filing_date": filing_date.date(),
                "report_type": report_type,
                "report_url": report_url,
                "filing_url": row.get("filing_url"),
                "accepted_date": None if pd.isna(accepted) else accepted,
            },
        )
        written += 1
    return written


def _populate_security(conn, security, statement_limit, include_dcf, include_filings, stats):
    """Fetch and store every FMP payload for one security; returns rows written."""
    ticker = security["ticker"]
    written = 0
    for statement in STATEMENT_TYPES:
        try:
            frame = financial_statements(ticker, statement=statement, limit=statement_limit)
        except Exception as exc:  # noqa: BLE001 - one statement must not stop the security
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error fetching {statement} statement for {ticker}: {exc}")
            continue
        if frame is None or frame.empty:
            stats["empty"] += 1
            continue
        for row in frame.to_dict("records"):
            written += upsert_statement(conn, security["security_id"], statement, row)
    if include_dcf:
        try:
            dcf = discounted_cash_flow(ticker)
        except Exception as exc:  # noqa: BLE001 - best-effort enrichment
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error fetching DCF for {ticker}: {exc}")
        else:
            if dcf:
                written += upsert_dcf(conn, security["security_id"], dcf)
    if include_filings:
        try:
            frame = filings(ticker)
        except Exception as exc:  # noqa: BLE001 - best-effort enrichment
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error fetching filings for {ticker}: {exc}")
        else:
            written += upsert_filings(conn, security["security_id"], frame)
    return written


def populate_fmp_fundamentals(
    tickers=None,
    limit=None,
    statement_limit=DEFAULT_STATEMENT_LIMIT,
    include_dcf=True,
    include_filings=True,
):
    """Gather FMP statements, DCF and filings for the dividend universe."""
    stats = {
        "securities": 0,
        "attempted": 0,
        "written": 0,
        "skipped": 0,
        "empty": 0,
        "errors": 0,
    }
    with engine.connect() as conn:
        securities = load_securities(conn, tickers=tickers, limit=limit)
    stats["securities"] = len(securities)
    print(f"  {len(securities)} active dividend securities target FMP fundamentals")
    if not securities:
        return stats
    if not _has_fmp_key():
        print(
            "  No FMP key configured; nothing to gather. Set fmp_api_key in "
            f"{settings.openbb_credentials_file}."
        )
        stats["skipped"] = len(securities)
        return stats

    for index, security in enumerate(securities, 1):
        stats["attempted"] += 1
        try:
            with engine.begin() as conn:
                stats["written"] += _populate_security(
                    conn, security, statement_limit, include_dcf, include_filings, stats
                )
        except Exception as exc:  # noqa: BLE001 - one security must not stop the run
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  Error storing FMP fundamentals for {security['ticker']}: {exc}")
        if index % 100 == 0:
            print(
                f"  Progress: {index}/{len(securities)} securities, "
                f"rows={stats['written']}, errors={stats['errors']}",
                flush=True,
            )
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 'AAPL,MSFT'")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to the first N securities (for testing)"
    )
    parser.add_argument(
        "--statement-limit",
        type=int,
        default=DEFAULT_STATEMENT_LIMIT,
        help="Fiscal periods per statement type (default 5)",
    )
    parser.add_argument("--skip-dcf", action="store_true", help="Do not gather the DCF estimate")
    parser.add_argument(
        "--skip-filings", action="store_true", help="Do not gather FMP company filings"
    )
    args = parser.parse_args()
    tickers = (
        [value.strip().upper() for value in args.tickers.split(",") if value.strip()]
        if args.tickers
        else None
    )
    try:
        stats = populate_fmp_fundamentals(
            tickers=tickers,
            limit=args.limit,
            statement_limit=args.statement_limit,
            include_dcf=not args.skip_dcf,
            include_filings=not args.skip_filings,
        )
    except Exception as exc:
        print(f"✗ Error populating FMP fundamentals: {exc}", file=sys.stderr)
        return 1
    print(
        f"\nFMP fundamentals: securities={stats['securities']}, "
        f"rows written={stats['written']}, empty={stats['empty']}, "
        f"errors={stats['errors']}, skipped={stats['skipped']}"
    )
    return stage_exit_code(
        "populate_fmp_fundamentals",
        stats["attempted"],
        stats["written"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )


if __name__ == "__main__":
    sys.exit(main())
