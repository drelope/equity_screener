"""
Repair per-series terms contaminated by issuer-level SEC XBRL facts.

Earlier versions of ``populate_raw_tables`` copied SEC Company Facts terms into
``raw.ticker_profile.coupon_rate`` / ``liquidation_preference`` whenever the
security title did not parse. Those facts are issuer-level (no series
dimension) and the extractor falls back to *par value* concepts, so thousands
of common and preferred rows carried 0.01 / 0.0001 "liquidation preferences".
``COALESCE(new, old)`` then made the bad values permanent, and they were copied
into ``reference.securities``.

This job, which is DB-only and idempotent:

1. Re-derives the per-series terms for every ``raw.ticker_profile`` row from
   ``reference.securities.security_name`` plus the stored OpenBB names, with
   the same pure parser the nightly writers use. Only a ``coupon_rate`` /
   ``liquidation_preference`` whose stored value equals the issuer-level SEC
   value kept in ``raw_payload.sec_xbrl`` (and differs from the parse) is
   replaced, together with the ``coupon_type`` derived from a replaced coupon.
   A sub-$1 liquidation preference (a nominal par value, from either source)
   is also re-derived. Values from other writers (e.g. prospectus terms) are
   never touched. Each
   correction goes through the shared store owning only the repaired columns,
   so the load history records it.
2. Resets ``reference.securities.coupon_rate`` / ``liquidation_preference``
   to the re-parsed value where the current value equals the issuer-level SEC
   value (or is a sub-$1 nominal par) and is not backed by the name parse or (for liquidation preference)
   by ``preferred.contract_terms``.
3. Allocates the issuer-level SEC XBRL ``coupon_rate`` to a preferred whose CIK
   has exactly one active preferred. The fact is filed once per CIK with no
   series dimension, so it is ambiguous when an issuer has several preferreds
   but unambiguous when it has only one; the name parse still wins, so this
   only fills a blank.

Step 1 also re-parses name-derived columns that a later, better security name
has made stale (see ``stale_name_columns``). This job runs after every
security-name writer in the nightly, so the profile and the name agree even
when the rename lands after the profile fetch.

Usage:
    python -m scripts.repair_ticker_profile_sec_terms --dry-run
    python -m scripts.repair_ticker_profile_sec_terms
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.populate_dividend_data import MIN_PAR_AS_LIQUIDATION, summarize_ticker_profile
from src.crispdm.db import engine
from src.crispdm.ticker_profile_store import NAME_PARSE_COLUMNS, upsert_ticker_profile

LOADER = "repair_ticker_profile_sec_terms"
SEC_TERM_COLUMNS = ("coupon_rate", "liquidation_preference")


def _get_singleton_ciks(conn):
    rows = conn.execute(
        text(
            """
            SELECT s.cik
            FROM reference.securities s
            WHERE s.active AND s.security_type = 'preferred stock'
            GROUP BY s.cik
            HAVING count(*) = 1
            """
        )
    ).fetchall()
    return {r[0] for r in rows if r[0]}


LOAD_ROWS_SQL = """
SELECT tp.security_id, tp.ticker, tp.provider,
       s.security_name, s.security_type AS reference_security_type, s.cik, s.active,
       tp.raw_payload -> 'openbb' AS openbb,
       tp.raw_payload -> 'sec_xbrl' AS sec_xbrl,
       tp.field_sources,
       {columns}
FROM raw.ticker_profile tp
LEFT JOIN reference.securities s ON s.security_id = tp.security_id
ORDER BY tp.security_id
"""

#: Loaders whose name-parse columns are exactly the parse of the security name
#: at the time (None: rows written before field_sources was recorded).
NAME_PARSE_WRITERS = (None, "populate_dividend_data", "populate_raw_tables")

REFERENCE_REPAIR_SQL = """
WITH sec AS (
    SELECT tp.security_id,
           tp.coupon_rate AS parsed_coupon,
           tp.liquidation_preference AS parsed_liquidation,
           CASE WHEN jsonb_typeof(tp.raw_payload -> 'sec_xbrl' -> 'coupon_rate') = 'number'
                THEN (tp.raw_payload -> 'sec_xbrl' ->> 'coupon_rate')::numeric END AS sec_coupon,
           CASE WHEN jsonb_typeof(tp.raw_payload -> 'sec_xbrl' -> 'liquidation_preference') = 'number'
                THEN (tp.raw_payload -> 'sec_xbrl' ->> 'liquidation_preference')::numeric
           END AS sec_liquidation,
           ct.liquidation_preference AS contract_liquidation
    FROM raw.ticker_profile tp
    LEFT JOIN preferred.contract_terms ct ON ct.security_id = tp.security_id
),
fix AS (
    SELECT s.security_id,
           (s.coupon_rate = sec.sec_coupon
            AND s.coupon_rate IS DISTINCT FROM sec.parsed_coupon) AS fix_coupon,
           ((s.liquidation_preference = sec.sec_liquidation
             OR s.liquidation_preference < 1)
            AND s.liquidation_preference IS DISTINCT FROM sec.parsed_liquidation
            AND s.liquidation_preference IS DISTINCT FROM sec.contract_liquidation)
               AS fix_liquidation,
           sec.parsed_coupon, sec.parsed_liquidation
    FROM reference.securities s
    JOIN sec ON sec.security_id = s.security_id
)
{action}
"""

REFERENCE_COUNT_ACTION = """
SELECT count(*) FILTER (WHERE fix_coupon) AS coupon_rows,
       count(*) FILTER (WHERE fix_liquidation) AS liquidation_rows
FROM fix
"""

REFERENCE_UPDATE_ACTION = """
UPDATE reference.securities s
SET coupon_rate = CASE WHEN fix.fix_coupon THEN fix.parsed_coupon ELSE s.coupon_rate END,
    liquidation_preference = CASE WHEN fix.fix_liquidation THEN fix.parsed_liquidation
                                  ELSE s.liquidation_preference END,
    updated_at = now()
FROM fix
WHERE fix.security_id = s.security_id
  AND (fix.fix_coupon OR fix.fix_liquidation)
"""


def _same(left, right):
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        return Decimal(str(left)) == Decimal(str(right))
    return str(left) == str(right)


def reparse_row(row):
    """Return the re-derived name-parse values for one stored profile row."""
    openbb = row.get("openbb") if isinstance(row.get("openbb"), dict) else {}
    summary = summarize_ticker_profile(
        row["ticker"], row.get("security_name"), row.get("reference_security_type"), openbb
    )
    return {column: summary[column] for column in NAME_PARSE_COLUMNS}


def _sec_value(row, column):
    sec = row.get("sec_xbrl")
    value = sec.get(column) if isinstance(sec, dict) else None
    return (
        value if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else None
    )


def changed_columns(row, parsed, lone_preferred=False):
    """Return the columns whose stored value is the issuer-level SEC leak.

    A lone preferred (its CIK has exactly one active preferred) legitimately
    owns its issuer's single coupon fact, so a ``coupon_rate`` equal to that
    fact is an allocation, not a leak, and is left alone. Liquidation
    preferences are never allocated, so their check always applies.
    """
    changed = []
    for column in SEC_TERM_COLUMNS:
        if column == "coupon_rate" and lone_preferred:
            continue
        if (
            row.get(column) is not None
            and _sec_value(row, column) is not None
            and _same(row.get(column), _sec_value(row, column))
            and not _same(row.get(column), parsed[column])
        ):
            changed.append(column)
    # A sub-$1 "liquidation preference" is a nominal par value, whichever
    # source (SEC fact or the old title parser) put it there.
    stored = row.get("liquidation_preference")
    if (
        "liquidation_preference" not in changed
        and stored is not None
        and Decimal(str(stored)) < Decimal(str(MIN_PAR_AS_LIQUIDATION))
        and not _same(stored, parsed["liquidation_preference"])
    ):
        changed.append("liquidation_preference")
    if "coupon_rate" in changed and not _same(row.get("coupon_type"), parsed["coupon_type"]):
        changed.append("coupon_type")
    return changed


def stale_name_columns(row, parsed):
    """Return the name-parse columns that no longer match the current security name.

    The columns are parsed from ``reference.securities.security_name`` when the
    profile is fetched, so a later, better name (the SEC cover title written by
    ``populate_sec_instrument_titles``, or a rename by the classification
    repair) leaves them stale until the next fetch: ABR-PD kept the issuer
    name "ARBOR REALTY TRUST INC" as its series and ABR-PF ``fixed`` for a
    Fixed-to-Floating title. A column last written by the name parser takes the
    new parse, blank included. A column another loader set (an allocated SEC
    coupon, a title-filled blank) is only replaced by a non-blank parse: the
    name parse wins, but never erases another source's value.
    """
    sources = row.get("field_sources") or {}
    stale = [
        column
        for column in NAME_PARSE_COLUMNS
        if not _same(row.get(column), parsed[column])
        and (sources.get(column) in NAME_PARSE_WRITERS or parsed[column] is not None)
    ]
    if "coupon_rate" in stale and "coupon_type" not in stale:
        if not _same(row.get("coupon_type"), parsed["coupon_type"]):
            stale.append("coupon_type")
    return stale


def allocation_columns(row, singleton):
    """Return the issuer-level SEC terms safe to assign to a lone preferred.

    Only ``coupon_rate`` (and the ``coupon_type`` it implies) is allocated. The
    SEC XBRL coupon is filed once per CIK without a series dimension, so it can
    only be attributed when the CIK has exactly one active preferred; a value
    parsed from the title always wins, so this fills a blank, never overwrites.
    """
    if not singleton or row.get("reference_security_type") != "preferred stock":
        return {}
    if not row.get("active"):
        return {}
    if row.get("coupon_rate") is not None:
        return {}
    parsed = reparse_row(row)
    if parsed["coupon_rate"] is not None:
        return {}
    sec_coupon = _sec_value(row, "coupon_rate")
    if sec_coupon is None:
        return {}
    return {"coupon_rate": sec_coupon, "coupon_type": parsed["coupon_type"] or "fixed"}


def repair(conn):
    rows = [
        dict(row)
        for row in conn.execute(
            text(LOAD_ROWS_SQL.format(columns=", ".join(f"tp.{c}" for c in NAME_PARSE_COLUMNS)))
        )
        .mappings()
        .all()
    ]
    column_changes = dict.fromkeys((*SEC_TERM_COLUMNS, "coupon_type"), 0)
    refreshed_columns = dict.fromkeys(NAME_PARSE_COLUMNS, 0)
    singleton_ciks = _get_singleton_ciks(conn)
    repaired = refreshed = 0
    for row in rows:
        parsed = reparse_row(row)
        changed = changed_columns(row, parsed, lone_preferred=row.get("cik") in singleton_ciks)
        stale = [column for column in stale_name_columns(row, parsed) if column not in changed]
        if not changed and not stale:
            continue
        if changed:
            repaired += 1
        if stale:
            refreshed += 1
        for column in changed:
            column_changes[column] += 1
        for column in stale:
            refreshed_columns[column] += 1
        owned = changed + stale
        upsert_ticker_profile(
            conn,
            {
                "security_id": row["security_id"],
                "ticker": row["ticker"],
                "provider": row["provider"],
                "raw_payload": {},
                **{column: parsed[column] for column in owned},
            },
            loader=LOADER,
            owned_columns=owned,
            refreshed=False,
        )
        # The allocation pass below reads these rows, so it must see the repair.
        row.update({column: parsed[column] for column in owned})

    counts = (
        conn.execute(text(REFERENCE_REPAIR_SQL.format(action=REFERENCE_COUNT_ACTION)))
        .mappings()
        .one()
    )
    conn.execute(text(REFERENCE_REPAIR_SQL.format(action=REFERENCE_UPDATE_ACTION)))

    # Allocation runs last: it must not be undone by the leak repair, which
    # would see the freshly written coupon as an unrebacked SEC value.
    allocated = 0
    allocated_columns = dict.fromkeys(("coupon_rate", "coupon_type"), 0)
    reference_allocated = 0
    for row in rows:
        allocation = allocation_columns(row, row.get("cik") in singleton_ciks)
        if not allocation:
            continue
        allocated += 1
        for column in allocation:
            allocated_columns[column] += 1
        upsert_ticker_profile(
            conn,
            {
                "security_id": row["security_id"],
                "ticker": row["ticker"],
                "provider": row["provider"],
                "raw_payload": {},
                **allocation,
            },
            loader=LOADER,
            owned_columns=tuple(allocation),
            refreshed=False,
        )
        reference_allocated += conn.execute(
            text("""
                UPDATE reference.securities
                SET coupon_rate = COALESCE(coupon_rate, :coupon_rate), updated_at = now()
                WHERE security_id = :security_id AND security_type = 'preferred stock'
            """),
            {"coupon_rate": allocation["coupon_rate"], "security_id": row["security_id"]},
        ).rowcount

    return {
        "profiles_scanned": len(rows),
        "profiles_repaired": repaired,
        "column_changes": column_changes,
        "profiles_refreshed": refreshed,
        "refreshed_columns": refreshed_columns,
        "profiles_allocated": allocated,
        "allocated_columns": allocated_columns,
        "reference_allocated_rows": reference_allocated,
        "reference_coupon_rows": counts["coupon_rows"],
        "reference_liquidation_rows": counts["liquidation_rows"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = parser.parse_args(argv)

    # A dry run executes the full repair and rolls it back, so the reported
    # reference counts reflect the re-parsed profile values exactly.
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            result = repair(conn)
        except Exception:
            transaction.rollback()
            raise
        if args.dry_run:
            transaction.rollback()
        else:
            transaction.commit()

    label = "DRY RUN" if args.dry_run else "REPAIRED"
    print(f"[{label}] scanned {result['profiles_scanned']} raw.ticker_profile rows")
    print(f"  profiles with SEC-leaked terms repaired: {result['profiles_repaired']}")
    for column, count in result["column_changes"].items():
        if count:
            print(f"    {column}: {count}")
    print(f"  profiles re-parsed from a changed security name: {result['profiles_refreshed']}")
    for column, count in result["refreshed_columns"].items():
        if count:
            print(f"    {column}: {count}")
    print(
        f"  lone-preferred profiles allocated an issuer-level SEC coupon: {result['profiles_allocated']}"
    )
    for column, count in result["allocated_columns"].items():
        if count:
            print(f"    {column}: {count}")
    print(
        "  reference.securities SEC-contaminated rows: "
        f"coupon_rate={result['reference_coupon_rows']}, "
        f"liquidation_preference={result['reference_liquidation_rows']}"
    )
    print(f"  reference.securities rows given a coupon: {result['reference_allocated_rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
