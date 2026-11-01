"""SEC XBRL Frames: cross-sectional snapshots and peer statistics.

The Frames API returns one concept for every filer over one calendar period.
``raw.xbrl_frames`` stores those snapshots so a peer median is a query, not a loop
of per-company calls.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .db import read_df

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json"

#: (taxonomy, concept, unit, kind) -- the primary tags behind the model's financial
#: inputs (see ``xbrl_tags.PERIODIC_FINANCIAL_CONCEPT_TAGS``). ``instant`` concepts are
#: balance-sheet amounts at a date; ``duration`` concepts are flows over a period.
FRAME_CONCEPTS: tuple[tuple[str, str, str, str], ...] = (
    ("us-gaap", "Assets", "USD", "instant"),
    ("us-gaap", "Liabilities", "USD", "instant"),
    ("us-gaap", "StockholdersEquity", "USD", "instant"),
    ("us-gaap", "LongTermDebt", "USD", "instant"),
    ("us-gaap", "NetIncomeLoss", "USD", "duration"),
    ("us-gaap", "Revenues", "USD", "duration"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD", "duration"),
    ("us-gaap", "InterestExpense", "USD", "duration"),
    ("us-gaap", "CommonStockDividendsPerShareDeclared", "USD-per-shares", "duration"),
)

PEER_SQL = """
SELECT count(*) AS peers,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.value)::float8 AS median,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY f.value)::float8 AS p25,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY f.value)::float8 AS p75
FROM raw.xbrl_frames f
JOIN reference.issuers i ON i.cik = f.cik
WHERE f.taxonomy = :taxonomy AND f.concept = :concept AND f.unit = :unit
  AND f.period = :period
  AND left(i.sic, :digits) = (SELECT left(sic, :digits) FROM reference.issuers WHERE cik = :cik)
  AND f.cik <> :cik
"""


def period_code(year: int, quarter: int | None = None, instant: bool = False) -> str:
    """Frames period code: ``CY2023``, ``CY2023Q4`` or ``CY2023Q4I``.

    An instant concept needs a quarter (it is a balance at a quarter end).
    """
    if quarter is None:
        if instant:
            raise ValueError("an instant frame needs a quarter")
        return f"CY{year}"
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    return f"CY{year}Q{quarter}" + ("I" if instant else "")


def default_periods(kind: str, today: date | None = None, years: int = 5) -> list[str]:
    """Completed periods worth snapshotting: recent annual years, or year-end instants."""
    today = today or date.today()
    last = today.year - 1  # the most recent completed calendar year
    codes = [
        period_code(y, 4, instant=True) if kind == "instant" else period_code(y)
        for y in range(last - years + 1, last + 1)
    ]
    return codes


def rows_from_frame(
    taxonomy: str, concept: str, unit: str, period: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Insert parameters from a frames payload; one row per filer, bad rows dropped."""
    rows: dict[str, dict[str, Any]] = {}
    for fact in payload.get("data", []):
        try:
            cik = str(int(fact["cik"])).zfill(10)
            value = float(fact["val"])
        except (KeyError, ValueError, TypeError):
            continue
        end = pd.to_datetime(fact.get("end"), errors="coerce")
        rows[cik] = {
            "taxonomy": taxonomy,
            "concept": concept,
            "unit": unit,
            "period": period,
            "cik": cik,
            "entity_name": fact.get("entityName"),
            "value": value,
            "period_end": None if pd.isna(end) else end.date(),
            "accession": fact.get("accn"),
        }
    return list(rows.values())


def peer_stats(
    concept: str,
    period: str,
    cik: str,
    unit: str = "USD",
    taxonomy: str = "us-gaap",
    sic_digits: int = 2,
    query=read_df,
) -> dict[str, float | int | None]:
    """Median and quartiles of ``concept`` across filers sharing ``cik``'s SIC prefix.

    The filer itself is excluded. ``sic_digits`` is the prefix length (2 = SIC major
    group). Returns ``peers = 0`` and ``None`` statistics when no peer has a value.
    """
    frame = query(
        PEER_SQL,
        {
            "taxonomy": taxonomy,
            "concept": concept,
            "unit": unit,
            "period": period,
            "digits": sic_digits,
            "cik": str(int(cik)).zfill(10),
        },
    )
    row = frame.iloc[0]
    peers = int(row["peers"])
    return {
        "peers": peers,
        "median": None if not peers else float(row["median"]),
        "p25": None if not peers else float(row["p25"]),
        "p75": None if not peers else float(row["p75"]),
    }
