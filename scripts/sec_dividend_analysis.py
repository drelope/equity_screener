"""
Analyze SEC XBRL security type and dividend-related tags for all tickers.

Output is intentionally slim: for each ticker, only the security type and
dividend information are returned (ticker is kept as the row identifier).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.sec_client import SEC_SESSION
from src.crispdm.xbrl_tags import DIVIDEND_TAGS as _REGISTRY_DIVIDEND_TAGS

# Dividend-related SEC XBRL tags (canonical set in src.crispdm.xbrl_tags).
# Some tags may not exist for every company.
DIVIDEND_TAGS = {tag: owner for tag, owner in _REGISTRY_DIVIDEND_TAGS.items()}

# Columns kept in the final output. Everything else (CIK, unit, form,
# filed date, etc.) is dropped from the returned dataset.
OUTPUT_COLUMNS = [
    "ticker",
    "security_type",
    "pays_dividend",
    "latest_dividend_value",
    "latest_dividend_period_end",
]


def sec_get(url):
    """GET JSON from SEC with exponential backoff and throttling."""
    response = SEC_SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def get_sec_tickers():
    """
    Download SEC's company ticker mapping.

    Returns columns:
        cik
        ticker
        company_name
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    data = sec_get(url)

    rows = []
    for item in data.values():
        rows.append(
            {
                "cik": str(item["cik_str"]).zfill(10),
                "ticker": item["ticker"].upper(),
                "company_name": item["title"],
            }
        )

    return pd.DataFrame(rows).drop_duplicates(["cik", "ticker"])


def get_company_facts(cik):
    """Download Company Facts JSON for one SEC CIK."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
    return sec_get(url)


def extract_dividend_facts(company_facts, lookback_days=5480):
    """
    Extract positive dividend-related facts from the last approximately
    18 months.

    Returns:
        dividend evidence rows
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    facts = company_facts.get("facts", {})

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
                    except ValueError:
                        continue

                    if end_as_date < cutoff:
                        continue

                    evidence.append(
                        {
                            "xbrl_tag": full_tag,
                            "security_type_from_tag": inferred_type,
                            "value": numeric_value,
                            "period_end": end_date,
                        }
                    )

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


def analyze_ticker(cik, ticker):
    """
    Analyze one CIK/ticker pair.

    Returns only security type and dividend information for that ticker.
    """
    try:
        company_facts = get_company_facts(cik)
        evidence = extract_dividend_facts(company_facts)

        if evidence:
            latest = sorted(
                evidence,
                key=lambda row: row.get("period_end") or "",
                reverse=True,
            )[0]

            return {
                "ticker": ticker,
                "security_type": classify_security_type(evidence),
                "pays_dividend": True,
                "latest_dividend_value": latest["value"],
                "latest_dividend_period_end": latest["period_end"],
            }

        return {
            "ticker": ticker,
            "security_type": "Unknown",
            "pays_dividend": False,
            "latest_dividend_value": None,
            "latest_dividend_period_end": None,
        }

    except requests.HTTPError:
        return {
            "ticker": ticker,
            "security_type": "Error",
            "pays_dividend": None,
            "latest_dividend_value": None,
            "latest_dividend_period_end": None,
        }

    except Exception:
        return {
            "ticker": ticker,
            "security_type": "Error",
            "pays_dividend": None,
            "latest_dividend_value": None,
            "latest_dividend_period_end": None,
        }


def build_dividend_dataset(tickers=None, max_companies=None):
    """
    Build one unique row per ticker, containing only security type and
    dividend information.

    Parameters:
        tickers:
            Optional list such as ["AAPL", "MSFT", "KO"].
            If None, process all SEC-listed tickers.
        max_companies:
            Optional limit for testing.
    """
    ticker_df = get_sec_tickers()

    if tickers:
        requested = {ticker.upper() for ticker in tickers}
        ticker_df = ticker_df[ticker_df["ticker"].isin(requested)]

    ticker_df = ticker_df.drop_duplicates(["cik", "ticker"])

    if max_companies:
        ticker_df = ticker_df.head(max_companies)

    results = []

    for row in ticker_df.itertuples(index=False):
        print(f"Processing {row.ticker} - CIK {row.cik}")

        results.append(analyze_ticker(cik=row.cik, ticker=row.ticker))

    return pd.DataFrame(results, columns=OUTPUT_COLUMNS)


if __name__ == "__main__":
    # Test with selected securities first.
    result = build_dividend_dataset(
        tickers=["LFMDP", "ACR-PD", "ACR-PC"],
    )

    print(result.to_string(index=False))

    result.to_csv("sec_dividend_analysis.csv", index=False)
