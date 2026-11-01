"""Re-sync reference.security_identifiers from reference.securities.

V0098 backfilled the table once. Run this after anything that fills ``cik``,
``ticker``, ``cusip`` or ``isin`` on ``reference.securities`` (for example a
provider CUSIP/ISIN lookup), so the identifier history picks the new values up.
Existing rows are untouched, so it is safe to repeat.

    python -m scripts.sync_security_identifiers
"""

from __future__ import annotations

from sqlalchemy import text

from src.crispdm.db import engine
from src.crispdm.identity import identifier_coverage

#: (id_type, expression that yields the stored form)
SOURCES = (
    ("cik", "cik"),
    ("ticker", "upper(ticker)"),
    ("cusip", "upper(cusip)"),
    ("isin", "upper(isin)"),
)


def sync() -> dict[str, int]:
    inserted = {}
    with engine.begin() as conn:
        for id_type, expression in SOURCES:
            column = expression.removeprefix("upper(").removesuffix(")")
            result = conn.execute(
                text(
                    f"""
                    INSERT INTO reference.security_identifiers
                      (security_id, id_type, id_value, valid_to, source)
                    SELECT security_id, '{id_type}', {expression}, delisted_date,
                           'reference.securities'
                    FROM reference.securities
                    WHERE {column} IS NOT NULL AND btrim({column}) <> ''
                    ON CONFLICT DO NOTHING
                    """  # noqa: S608 - both interpolated values come from the constant above
                )
            )
            inserted[id_type] = result.rowcount
    return inserted


def main() -> int:
    print("inserted:", sync())
    print("coverage:", identifier_coverage())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
