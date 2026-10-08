"""Which securities count as dividend payers: a recent XBRL tag, or a payment we have seen.

The XBRL tag alone is a weak signal: any concept whose name contains "dividend" counts,
including dividends *received*, payables and balance-sheet items. With recency enforced
(``ENFORCE_DIVIDEND_RECENCY``) a stale tag no longer qualifies, but an issuer's tags can
lag its payments: 157 securities with a payment in the stored series had a last tag older
than the window. A payment actually observed in ``raw.dividend_data`` therefore keeps a
security flagged.

Observed payments only keep an existing payer. A new one has to be found by its tags,
because dividends are only fetched for securities that are already flagged.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from .config import settings


def observed_payer_keys(conn, *, today: date | None = None) -> set[tuple[str, str]]:
    """``(cik, ticker)`` of every security with a positive payment inside the recency window.

    Empty when recency is not enforced: the classifier then flags on any positive fact
    ever filed, so the override has nothing to add and the legacy behaviour is unchanged.
    """
    if not settings.enforce_dividend_recency:
        return set()
    today = today or date.today()
    since = today - timedelta(days=settings.dividend_recency_days)
    rows = conn.execute(
        text("""
        SELECT DISTINCT s.cik, s.ticker
        FROM raw.dividend_data d
        JOIN reference.securities s ON s.security_id = d.security_id
        WHERE d.amount > 0 AND d.ex_dividend_date BETWEEN :since AND :today
    """),
        {"since": since, "today": today},
    )
    return {(row[0], row[1]) for row in rows}
