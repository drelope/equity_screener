"""
Build a preferred-dividend snapshot dataset from the raw.companyfacts table.

Reads the SEC XBRL companyfacts payloads already stored in PostgreSQL (loaded
by scripts.populate_companyfacts), extracts dividend-related tags for each
security, and infers the security type.

Writes one row per security to preferred.dividend_snapshot (upserted on
security_id) and optionally dumps the same rows to CSV.

No SEC requests are made: this script consumes only data already ingested
into the raw.companyfacts table.

Usage:
    python -m scripts.sec_xbrl_dividend_tags
    python -m scripts.sec_xbrl_dividend_tags --tickers ACR-PD,ACR-PC
    python -m scripts.sec_xbrl_dividend_tags --preferred-only --csv out.csv
    python -m scripts.sec_xbrl_dividend_tags --max 100 --lookback-days 1096
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.xbrl_tags import DIVIDEND_TAGS

OUTPUT_COLUMNS = [
    "security_id",
    "ticker",
    "cik",
    "preferred_flag",
    "pays_dividend",
    "active",
    "dividend_evidence_tag",
    "latest_dividend_period_end",
    "latest_dividend_filed",
    "latest_dividend_form",
]


def extract_dividend_facts(facts, lookback_days=548):
    """
    Extract positive dividend-related facts from the last ``lookback_days``.

    ``facts`` is the SEC companyfacts taxonomy map (``raw_payload.facts``),
    e.g. ``{"us-gaap": {concept: {units: {unit: [...]}}}}``.

    Pass ``lookback_days=None`` to extract all historical evidence, which is
    used to decide whether an issuer has ever issued a dividend.

    Returns:
        dividend evidence rows
    """
    cutoff = None
    if lookback_days is not None:
        cutoff = date.today() - timedelta(days=lookback_days)
    evidence = []

    for taxonomy, taxonomy_facts in facts.items():
        for tag, tag_info in taxonomy_facts.items():
            full_tag = f"{taxonomy}:{tag}"

            if full_tag not in DIVIDEND_TAGS:
                continue

            inferred_type = DIVIDEND_TAGS[full_tag]

            for unit_name, observations in tag_info.get("units", {}).items():
                for observation in observations:
                    value = observation.get("val")
                    end_date = observation.get("end")
                    filed_date = observation.get("filed")

                    if value is None or end_date is None:
                        continue

                    try:
                        numeric_value = float(value)
                    except (TypeError, ValueError):
                        continue

                    # A positive dividend-related value is evidence of a dividend.
                    if numeric_value <= 0:
                        continue

                    try:
                        end_as_date = date.fromisoformat(end_date)
                    except (TypeError, ValueError):
                        continue

                    if cutoff is not None and end_as_date < cutoff:
                        continue

                    evidence.append({
                        "xbrl_tag": full_tag,
                        "security_type_from_tag": inferred_type,
                        "value": numeric_value,
                        "unit": unit_name,
                        "period_end": end_date,
                        "filed": filed_date,
                        "form": observation.get("form"),
                        "fp": observation.get("fp"),
                    })

    return evidence


def classify_security_type(evidence):
    """
    Infer the security type from dividend-related XBRL tags.
    """
    types = {
        row["security_type_from_tag"]
        for row in evidence
        if row["security_type_from_tag"] != "Unknown"
    }

    if types == {"Common Stock"}:
        return "Common Stock"

    if types == {"Preferred Stock"}:
        return "Preferred Stock"

    if len(types) > 1:
        return "Common and Preferred / Mixed"

    return "Unknown"


def _parse_payload(raw_payload):
    """Return the raw companyfacts payload as a dict."""
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        try:
            return json.loads(raw_payload)
        except (TypeError, ValueError):
            return {}
    return {}


def _facts_map(raw_payload):
    """Return the SEC taxonomy map from a companyfacts payload."""
    payload = _parse_payload(raw_payload)
    return payload.get("facts", payload)


def analyze_security(row, lookback_days=548):
    """
    Analyze one raw.companyfacts row (joined with reference.securities).

    Returns a dict matching the preferred.dividend_snapshot columns, or
    ``None`` when the issuer has no positive dividend evidence (such rows are
    not stored). ``pays_dividend`` marks issuers that have issued a dividend;
    ``active`` marks issuers with evidence inside the recent lookback window.
    """
    cik = row["cik"]
    ticker = row["ticker"]
    security_type = row.get("security_type") or "other"

    try:
        facts = _facts_map(row["raw_payload"])
        evidence = extract_dividend_facts(facts, lookback_days=None)
        inferred = classify_security_type(evidence)

        if not evidence:
            return None

        cutoff = date.today() - timedelta(days=lookback_days)
        active = any(
            (_parse_date(ev.get("period_end")) or date.min) >= cutoff
            for ev in evidence
        )

        latest = sorted(
            evidence,
            key=lambda ev: (
                ev.get("period_end") or "",
                ev.get("filed") or "",
            ),
            reverse=True,
        )[0]

        return {
            "security_id": row["security_id"],
            "ticker": ticker,
            "cik": cik,
            "preferred_flag": _is_preferred(security_type, inferred),
            "pays_dividend": True,
            "active": active,
            "dividend_evidence_tag": latest["xbrl_tag"],
            "latest_dividend_period_end": _parse_date(latest["period_end"]),
            "latest_dividend_filed": _parse_date(latest.get("filed")),
            "latest_dividend_form": latest.get("form"),
        }

    except Exception as exc:
        print(f"Skipping {ticker} (security_id {row['security_id']}): {exc}")
        return None


def _is_preferred(security_type, inferred_type):
    """True when either the reference or the XBRL-tag type is preferred."""
    if isinstance(security_type, str):
        normalized = security_type.lower()
        if normalized in ("preferred", "preferred stock"):
            return True
    if isinstance(inferred_type, str) and "preferred" in inferred_type.lower():
        return True
    return False


def _parse_date(value):
    """Best-effort ISO date string -> date, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.split("T", 1)[0])
        except (TypeError, ValueError):
            return None
    return None


def load_companyfacts_rows(tickers=None, preferred_only=False, max_companies=None):
    """Load raw.companyfacts rows joined with reference.securities.

    The stored SEC companyfacts payload is large, so rather than shipping the
    whole JSONB per row only the tags this pipeline consumes are extracted in
    SQL and rebuilt into a slim payload: the ``DIVIDEND_TAGS``.
    ``extract_dividend_facts`` reads exactly these tags, so results are
    unchanged.
    """
    clauses = ["s.active = TRUE"]
    params = {
        "needed_tags": sorted(
            {tag.split(":", 1)[1] for tag in DIVIDEND_TAGS}
        )
    }
    if tickers:
        clauses.append("UPPER(s.ticker) = ANY(:tickers)")
        params["tickers"] = [ticker.upper() for ticker in tickers]
    if preferred_only:
        clauses.append("LOWER(s.security_type) IN ('preferred', 'preferred stock')")
    where = " AND ".join(clauses)

    limit_sql = " LIMIT :max_companies" if max_companies is not None else ""
    if max_companies is not None:
        params["max_companies"] = max_companies

    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT DISTINCT ON (s.ticker)
                   s.security_id, s.ticker,
                   COALESCE(NULLIF(s.cik, ''), slim.cik) AS cik,
                   s.security_type,
                   slim.raw_payload
            FROM reference.securities s
            JOIN LATERAL (
                SELECT cf.cik,
                       jsonb_build_object(
                           'facts',
                           jsonb_build_object(
                               'us-gaap',
                               COALESCE(
                                   (SELECT jsonb_object_agg(e.k, e.v)
                                    FROM raw.companyfacts cf,
                                         jsonb_each(jsonb_extract_path(cf.raw_payload, 'facts', 'us-gaap')) AS e(k, v)
                                    WHERE cf.cik = s.cik
                                      AND e.k = ANY(:needed_tags)),
                                   '{{}}'::jsonb
                               )
                           )
                       ) AS raw_payload
                FROM raw.companyfacts cf
                WHERE cf.cik = s.cik
                  AND cf.cik IS NOT NULL
                LIMIT 1
            ) slim ON TRUE
            WHERE {where}
            ORDER BY s.ticker, s.updated_at DESC NULLS LAST
            {limit_sql}
        """), params).mappings().all()
    return rows


def build_preferred_dividend_dataset(tickers=None, preferred_only=False, max_companies=None, lookback_days=548):
    """
    Build one unique row per security from raw.companyfacts.

    Issuers without positive dividend evidence are skipped, so the DataFrame
    contains only dividend-issuing securities, each flagged active/inactive.

    Returns a pandas DataFrame with the preferred.dividend_snapshot columns.
    """
    rows = load_companyfacts_rows(
        tickers=tickers,
        preferred_only=preferred_only,
        max_companies=max_companies,
    )

    results = []
    for row in rows:
        print(f"Analyzing {row['ticker']} - security_id {row['security_id']}")
        result = analyze_security(row, lookback_days=lookback_days)
        if result is not None:
            results.append(result)

    df = pd.DataFrame(results, columns=OUTPUT_COLUMNS)
    df["preferred_flag"] = df["preferred_flag"].astype(bool)
    df["active"] = df["active"].astype(bool)
    return df


def persist_preferred_dividend_dataset(df, replace=False):
    """Upsert the snapshot rows into preferred.dividend_snapshot.

    When ``replace`` is True (a full sweep), rows for securities absent from
    the dataset are deleted so the table only holds current dividend-issuing
    preferred securities.
    """
    if df.empty:
        return 0

    rows = [
        {key: (None if pd.isna(value) else value) for key, value in record.items()}
        for record in df.to_dict(orient="records")
    ]

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO preferred.dividend_snapshot
                (security_id, ticker, cik, preferred_flag, pays_dividend,
                 active, dividend_evidence_tag, latest_dividend_period_end,
                 latest_dividend_filed, latest_dividend_form, retrieved_at)
            VALUES (:security_id, :ticker, :cik, :preferred_flag, :pays_dividend,
                    :active, :dividend_evidence_tag, :latest_dividend_period_end,
                    :latest_dividend_filed, :latest_dividend_form, now())
            ON CONFLICT (security_id) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                cik = EXCLUDED.cik,
                preferred_flag = EXCLUDED.preferred_flag,
                pays_dividend = EXCLUDED.pays_dividend,
                active = EXCLUDED.active,
                dividend_evidence_tag = EXCLUDED.dividend_evidence_tag,
                latest_dividend_period_end = EXCLUDED.latest_dividend_period_end,
                latest_dividend_filed = EXCLUDED.latest_dividend_filed,
                latest_dividend_form = EXCLUDED.latest_dividend_form,
                retrieved_at = now()
        """), rows)
        if replace:
            conn.execute(text(
                "DELETE FROM preferred.dividend_snapshot "
                "WHERE NOT (security_id = ANY(CAST(:ids AS uuid[])))"
            ), {"ids": df["security_id"].tolist()})
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. 'ACR-PD,ACR-PC'")
    parser.add_argument("--preferred-only", dest="preferred_only", action="store_true", default=True,
                        help="Only analyze securities whose reference type is preferred stock (default)")
    parser.add_argument("--all-types", dest="preferred_only", action="store_false",
                        help="Also analyze non-preferred securities")
    parser.add_argument("--max", type=int, default=None,
                        help="Limit to the first N securities (for testing)")
    parser.add_argument("--lookback-days", type=int, default=548,
                        help="Ignore dividend evidence older than this many days")
    parser.add_argument("--csv", default=None,
                        help="Write the dataset to this CSV path (default: none)")
    parser.add_argument("--no-db", action="store_true",
                        help="Do not write to preferred.dividend_snapshot")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] if args.tickers else None

    df = build_preferred_dividend_dataset(
        tickers=tickers,
        preferred_only=args.preferred_only,
        max_companies=args.max,
        lookback_days=args.lookback_days,
    )

    print("\nPreferred Dividend Snapshot:")
    print(df.to_string(index=False))

    csv_path = args.csv or "preferred_dividend_dataset.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nWrote {len(df)} rows to {csv_path}")

    if not args.no_db:
        full_sweep = tickers is None and args.max is None
        persisted = persist_preferred_dividend_dataset(df, replace=full_sweep)
        print(f"Upserted {persisted} rows into preferred.dividend_snapshot" +
              (" (full sweep: removed stale securities)" if full_sweep else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())