"""Point-in-time macro reads over ``raw.macro_series_vintages`` (ALFRED).

A backtest as of date D must see each observation as it stood on D: a later
revision is not yet known. ``as_of_series`` returns exactly that.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .db import read_df

AS_OF_SQL = """
SELECT DISTINCT ON (observation_date) observation_date, value::float8 AS value, vintage_date
FROM raw.macro_series_vintages
WHERE series_id = :series_id
  AND vintage_date <= :as_of
  AND observation_date <= :as_of
ORDER BY observation_date, vintage_date DESC
"""


def rows_from_alfred(
    series_id: str, unit: str, payload: dict[str, Any], provider: str = "ALFRED"
) -> list[dict[str, Any]]:
    """Insert parameters from an ALFRED ``series/observations`` payload.

    ``realtime_start`` is the vintage. FRED sends ``"."`` for a missing value, which
    is skipped. A row whose vintage precedes its observation is a data error (a value
    cannot be known before the period it describes) and is dropped.
    """
    rows = []
    for obs in payload.get("observations", []):
        try:
            value = float(obs["value"])
            observed = date.fromisoformat(obs["date"])
            vintage = date.fromisoformat(obs["realtime_start"])
        except (KeyError, ValueError, TypeError):
            continue
        if vintage < observed:
            continue
        rows.append(
            {
                "series_id": series_id,
                "observation_date": observed,
                "vintage_date": vintage,
                "value": value,
                "unit": unit,
                "source": "FRED",
                "provider": provider,
            }
        )
    return rows


def as_of_series(series_id: str, as_of: date, query=read_df) -> pd.DataFrame:
    """Each observation's value as known on ``as_of`` (latest vintage not after it)."""
    frame = query(AS_OF_SQL, {"series_id": series_id, "as_of": as_of})
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["observation_date", "value", "vintage_date"])
    return frame.reset_index(drop=True)
