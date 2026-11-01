"""Resolve securities through ``reference.security_identifiers``.

The table keeps every cik / cusip / isin / ticker a security has carried and the
interval it was valid, so a lookup can be answered as of a date instead of only
against today's ``reference.securities`` row.
"""

from __future__ import annotations

from datetime import date

from .db import read_df

ID_TYPES = ("cik", "cusip", "isin", "ticker")

RESOLVE_SQL = """
SELECT security_id::text AS security_id
FROM reference.security_identifiers
WHERE id_type = :id_type AND id_value = :id_value
  AND (valid_from IS NULL OR valid_from <= :as_of)
  AND (valid_to IS NULL OR valid_to >= :as_of)
ORDER BY valid_from DESC NULLS LAST, identifier_id
"""

COVERAGE_SQL = """
SELECT count(*) AS active,
       count(*) FILTER (WHERE has_cik) AS with_cik,
       count(*) FILTER (WHERE has_market_id) AS with_market_identifier,
       count(*) FILTER (WHERE has_cik AND has_market_id) AS fully_identified
FROM (
  SELECT s.security_id,
         bool_or(i.id_type = 'cik') AS has_cik,
         bool_or(i.id_type IN ('ticker', 'cusip', 'isin')) AS has_market_id
  FROM reference.securities s
  LEFT JOIN reference.security_identifiers i USING (security_id)
  WHERE s.active = TRUE
  GROUP BY s.security_id
) t
"""


def normalize(id_type: str, id_value: str) -> str:
    """The stored form: CIKs are 10-digit zero padded, everything else upper case."""
    if id_type not in ID_TYPES:
        raise ValueError(f"unknown identifier type {id_type!r}; expected one of {ID_TYPES}")
    value = str(id_value).strip()
    if id_type == "cik":
        return value.zfill(10)
    return value.upper()


def resolve_security_ids(
    id_type: str, id_value: str, as_of: date | None = None, query=read_df
) -> list[str]:
    """Security ids that carried the identifier on ``as_of`` (today when omitted).

    More than one id is returned when an identifier is shared, for example a CIK
    across the share classes of one issuer. A ticker reused by different companies
    over time resolves to the holder on that date.
    """
    frame = query(
        RESOLVE_SQL,
        {
            "id_type": id_type,
            "id_value": normalize(id_type, id_value),
            "as_of": as_of or date.today(),
        },
    )
    return [] if frame is None or frame.empty else list(frame["security_id"])


def identifier_coverage(query=read_df) -> dict[str, int]:
    """Counts behind the check "every active security has a CIK and a market identifier"."""
    row = query(COVERAGE_SQL, {}).iloc[0]
    return {key: int(row[key]) for key in row.index}
