"""Reclassify securities whose stored type is contradicted by decisive evidence.

Two accuracy problems, both repaired here without a schema change:

1. SPAC warrants, rights and units stored as ``preferred stock``. The SEC assigns
   one symbol per registered class: a trailing ``-W``/``-WS``/``-WT``/``-R`` is a
   warrant or right (``derivative``) and ``-U`` a unit (``other_debt_and_equity``),
   which is exactly what :func:`src.crispdm.sec_client.classify_security_symbol`
   returns. Many SPAC instruments carry these codes *without* a dash (``AACOW``,
   ``BDCIW``), so the classifier fell through to the weak ``concept_bag`` signal
   and stored them as preferred. A hyphenless ``...W`` / ``...R`` is only accepted
   here when its base symbol (the ticker without the trailing letter) exists for
   the same CIK, which rules out ordinary common tickers that merely end in W/R
   (``AEHR``, ``BMNR``). A ``dei`` instrument title naming a warrant/right/unit is
   accepted on its own as the strongest evidence.

2. Issuer name-parse terms leaking onto common stock. The dividend ETL parsed a
   coupon/liquidation out of a preferred-style issuer name and wrote it to every
   ticker of the issuer; 117 common rows carried a coupon. Common stock has no
   coupon or liquidation preference, so those columns are cleared.

It also drops implausibly large/small ``preferred.security_terms.dividend_rate``
values (a nominal $0.0001 par or a 33,500,000 aggregate read as a rate).

Exact CIK/ticker cover titles also correct common shares and listed notes that
were mistaken for preferreds. Those authoritative titles outrank symbol suffixes;
the repair preserves security IDs and stores the title and filing provenance.

Idempotent and DB-only. ``--dry-run`` runs the full repair and rolls back.

Usage:
    python -m scripts.repair_security_classification --dry-run
    python -m scripts.repair_security_classification
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine
from src.crispdm.sec_client import classify_instrument

LOADER = "repair_security_classification"

#: Reclassify active preferred rows that a suffix or a dei title proves are a
#: warrant/right/unit. The base-sibling gate applies only to hyphenless W/R codes.
RECLASSIFY_SQL = """
WITH candidate AS (
    SELECT s.security_id, s.cik, s.ticker, s.dividend,
           LEFT(s.ticker, LENGTH(s.ticker) - 1) AS base,
           (SELECT CASE
                       WHEN it.title ~* '\\m(warrant|right)' THEN 'derivative'
                       WHEN it.title ~* '\\munits?\\M'
                            AND it.title !~* '\\m(preferred|preference)\\M'
                            THEN 'other_debt_and_equity'
                   END
            FROM raw.sec_instrument_titles it
            WHERE it.cik = s.cik AND UPPER(it.ticker) = UPPER(s.ticker)
              AND (
                  it.title ~* '\\m(warrant|right)\\M'
                  OR (it.title ~* '\\munits?\\M'
                      AND it.title !~* '\\m(preferred|preference)\\M')
              )
            LIMIT 1) AS title_type,
           CASE
               WHEN s.ticker ~ '-W(S|T)?$' THEN 'derivative'
               WHEN s.ticker ~ '-R$' THEN 'derivative'
               WHEN s.ticker ~ '-U$' THEN 'other_debt_and_equity'
               WHEN s.ticker ~ '^[A-Z0-9]{3,5}W$' THEN 'derivative'
               WHEN s.ticker ~ '^[A-Z0-9]{3,5}R$' AND s.ticker !~ 'PR$'
                    THEN 'derivative'
               WHEN s.ticker ~ '^[A-Z0-9]{1,5}U$' THEN 'other_debt_and_equity'
           END AS suffix_type
    FROM reference.securities s
    WHERE s.active AND s.security_type = 'preferred stock'
),
resolved AS (
    SELECT security_id, cik, ticker, dividend, base,
           COALESCE(title_type, suffix_type) AS new_type,
           title_type IS NOT NULL AS from_title
    FROM candidate
),
fix AS (
    SELECT c.security_id, c.ticker, c.new_type
    FROM resolved c
    WHERE c.new_type IS NOT NULL
      AND (
            -- A dei title naming a warrant/right/unit is decisive on its own; the
            -- base-sibling gate below only disambiguates the suffix heuristic.
            c.from_title
            OR c.new_type = 'other_debt_and_equity'
            OR c.ticker ~ '-[WRU]'
            OR EXISTS (
                SELECT 1 FROM reference.securities b
                WHERE b.cik = c.cik AND UPPER(b.ticker) = UPPER(c.base)
            )
          )
      AND NOT EXISTS (
          SELECT 1 FROM reference.securities d
          WHERE d.cik = c.cik AND d.ticker = c.ticker
            AND d.security_type = c.new_type AND d.dividend = c.dividend
            AND d.security_id <> c.security_id
      )
)
UPDATE reference.securities s
SET security_type = fix.new_type,
    classify_source = :loader,
    classify_confidence = 'medium',
    updated_at = now()
FROM fix
WHERE fix.security_id = s.security_id
RETURNING s.ticker, s.security_type
"""

#: Common stock has no coupon or liquidation preference; clear any carried over
#: from an issuer-name parse.
CLEAR_COMMON_LEAK_SQL = """
UPDATE reference.securities
SET coupon_rate = NULL,
    liquidation_preference = NULL,
    updated_at = now()
WHERE security_type = 'common_stock'
  AND (coupon_rate IS NOT NULL OR liquidation_preference IS NOT NULL)
RETURNING security_id
"""

#: A per-share preferred rate below $0.01 or above $1000 is a par artifact or an
#: aggregate, never a rate; drop it rather than show a wrongly precise figure.
CLEAR_ABSURD_RATE_SQL = """
UPDATE preferred.security_terms
SET dividend_rate = NULL
WHERE dividend_rate IS NOT NULL
  AND (dividend_rate < 0.01 OR dividend_rate > 1000)
RETURNING security_id
"""


def repair_exact_titles(conn):
    """Correct only instruments with a decisive, exact CIK/ticker cover title.

    Candidates are active rows typed ``preferred stock`` or ``common_stock``. A common row
    is the same kind of mistake: a note or unit listed under an issuer whose only other
    signal is a common-stock dividend tag (Navient's 6% Senior Notes, JSM, were typed
    common). The row is updated in place, so its ``security_id`` and every price, dividend
    and model row keyed on it stay attached; retyping it through the stage-1 insert would
    mint a new identity and strand them. A row is never moved to the type it already has.
    """
    rows = (
        conn.execute(
            text("""
        SELECT s.security_id, s.ticker, s.security_type AS current_type,
               t.title, t.accession_no, t.source_url
        FROM reference.securities s
        JOIN raw.sec_instrument_titles t ON t.cik = s.cik AND t.ticker = s.ticker
        WHERE s.active AND s.security_type IN ('preferred stock', 'common_stock')
    """)
        )
        .mappings()
        .all()
    )
    repaired = []
    for row in rows:
        decision = classify_instrument(row["ticker"], exact_dei_title=row["title"])
        if decision.security_type == row["current_type"]:
            continue
        if decision.source != "dei_title" or decision.security_type not in (
            "common_stock",
            "corporate bond",
            "government debt",
            "derivative",
            "other_debt_and_equity",
        ):
            continue
        evidence = json.dumps(
            {
                "exact_dei_title": row["title"],
                "accession_no": row["accession_no"],
                "source_url": row["source_url"],
                "evidence": decision.evidence,
                "conflicts": decision.conflicts,
            }
        )
        result = conn.execute(
            text("""
            UPDATE reference.securities s
            SET security_type = :new_type, security_name = :title,
                classify_source = 'dei_title', classify_confidence = 'high',
                classification_evidence = CAST(:evidence AS jsonb),
                liquidation_preference = NULL,
                coupon_rate = CASE WHEN :new_type IN ('common_stock', 'derivative',
                    'other_debt_and_equity') THEN NULL ELSE coupon_rate END,
                updated_at = now()
            WHERE s.security_id = :security_id
              AND NOT EXISTS (
                  SELECT 1 FROM reference.securities d
                  WHERE d.cik = s.cik AND d.ticker = s.ticker
                    AND d.security_type = :new_type AND d.dividend = s.dividend
                    AND d.security_id <> s.security_id
              )
            RETURNING s.ticker, s.security_type
        """),
            {**row, "new_type": decision.security_type, "evidence": evidence},
        ).all()
        if not result:
            # A row of the real type already holds the unique (cik, ticker, type,
            # dividend) key, so retire the misclassified preferred duplicate.
            result = conn.execute(
                text("""
                UPDATE reference.securities
                SET active = FALSE, classification_evidence = CAST(:evidence AS jsonb),
                    updated_at = now()
                WHERE security_id = :security_id
                RETURNING ticker, 'retired duplicate of ' || :new_type
            """),
                {**row, "new_type": decision.security_type, "evidence": evidence},
            ).all()
        repaired.extend(result)
    return repaired


def repair(conn):
    """Apply every repair; return the reclassified rows and a counts summary.

    Caller owns the transaction. The reclassified rows come straight from the
    UPDATE's RETURNING, so a re-run reports only what it actually changed rather
    than every row a previous run touched.
    """
    reclassified = repair_exact_titles(conn)
    reclassified.extend(conn.execute(text(RECLASSIFY_SQL), {"loader": LOADER}).all())
    cleared_leak = conn.execute(text(CLEAR_COMMON_LEAK_SQL)).all()
    cleared_rate = conn.execute(text(CLEAR_ABSURD_RATE_SQL)).all()
    summary = {
        "reclassified": len(reclassified),
        "cleared_common_leak": len(cleared_leak),
        "cleared_absurd_rate": len(cleared_rate),
    }
    return reclassified, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = parser.parse_args(argv)

    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            rows, summary = repair(conn)
        except Exception:
            transaction.rollback()
            raise
        if args.dry_run:
            transaction.rollback()
        else:
            transaction.commit()

    label = "DRY RUN" if args.dry_run else "REPAIRED"
    print(f"[{label}]")
    print(f"  reclassified exact-title/suffix rows: {summary['reclassified']}")
    for ticker, security_type in sorted(rows)[:40]:
        print(f"    {ticker:<8} -> {security_type}")
    if len(rows) > 40:
        print(f"    ... and {len(rows) - 40} more")
    print(f"  common-stock coupon/liquidation leaks cleared: {summary['cleared_common_leak']}")
    print(f"  implausible security_terms.dividend_rate cleared: {summary['cleared_absurd_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
