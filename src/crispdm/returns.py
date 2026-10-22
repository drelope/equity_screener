"""Forward total returns: what a holder earned over the window that followed a date.

The worksheet's "Historical analogs" step needs to know how an investment turned out over
the twelve months *after* a setup, for many securities, and it needs the answer to be a
total return rather than a price change. A dividend payer's income is part of what a
holder earned, so a price-only forward return would understate every payer and would
understate the payers this repository is about most.

The calculation mirrors ``features.build_features`` rather than inventing a second
definition of the same quantity, because two definitions of "12M total return" in one
warehouse is how a trailing momentum and a forward return stop being comparable. The
four rules that matter, and the failure each one prevents:

1. **Only the per-payment OPENBB dividend series is used.** ``raw.dividend_data`` holds
   both OPENBB (individual payments, with ex-dates) and SEC_XBRL (annual per-share totals
   whose ``ex_dividend_date`` is a fiscal period end). 2,561 securities have both, and
   summing them books one payment twice: KO's 2023-06-30 dividend lands as 0.92 instead
   of 0.46. The forward return is then inflated, and inflated more for the payers with
   the most stored history. ``features.py`` excludes XBRL from the return for exactly
   this reason; so does this module.

2. **A payment is booked to the first price row on or after its ex-date.** An ex-date can
   fall on a day the price series has no row (a weekend, or a gap in the stored history),
   and a join on equality would silently drop the payment rather than move it.

3. **A payment larger than the prior close is a unit or currency error and is left out of
   the return** (``MAX_SINGLE_PAYMENT_RATIO``). 19 of the stored payment events are
   impossible, one of them 2.1 million per share, and a single such row turns a 12M
   return into a number no holder ever earned. It is left out of the return rather than
   discarding the whole security, because one bad event says nothing about the other 251
   days.

4. **The window must be complete.** ``SUM(...) OVER (ROWS BETWEEN 1 FOLLOWING AND 252
   FOLLOWING)`` returns a *partial* sum when fewer than 252 rows follow, so a 29-day
   window would be reported as a 12-month return. The sample count is therefore required
   to equal the window, exactly as ``features.py`` requires 252 samples before it calls
   anything a 252-day volatility.

``raw.market_data.adjusted_close`` is entirely NULL, so close plus dividends is the only
route to a total return; the dividend is credited on its ex-date (when the price drops by
it, so the two cancel) and the daily logs are summed and exponentiated, which treats the
dividend as reinvested at the close of its ex-date.

A forward return is knowable only once the window has closed, so the materialised range
ends 252 trading days before the last stored price. That lag is the feature, not a defect:
a base rate built from returns that had not happened yet would be a forecast dressed as
history.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text

from .db import engine, read_df

#: Trading observations in a one-year window. The same horizon the trailing
#: ``momentum_252d`` feature uses, so a forward return and a trailing return are
#: measured over comparable spans.
FORWARD_WINDOW_DAYS = 252

#: A single dividend larger than the prior close is a unit or currency error and is
#: left out of the total-return calculation. Special dividends of 30-50% of price are
#: real and are kept; only an impossible payment is dropped. Shares the value with
#: ``features.MAX_SINGLE_PAYMENT_RATIO`` because it is the same rule about the same
#: payments.
MAX_SINGLE_PAYMENT_RATIO = 1.0

#: Rows per insert batch. The forward table is roughly ten times the size of the
#: feature table, so the batches are larger to keep the number of round trips down
#: without holding a whole table's worth of parameters in memory at once.
FORWARD_CHUNK_SIZE = 50_000

FORWARD_COLUMNS = (
    "security_id",
    "as_of_date",
    "forward_date",
    "window_days",
    "total_return",
    "price_return",
    "dividend_return",
)

#: The forward-return query.
#:
#: ``r`` computes two daily log returns per price row: one for the price alone and one
#: for the price plus the dividend credited that day. The price-only series exists so
#: the worksheet can say how much of a holder's return was income and how much was
#: price; the total series is the number that answers "what did a holder earn".
#:
#: ``fwd`` turns each row's daily log return into a forward window. Both the sum and
#: the count are window functions over the same frame, so the count says exactly how
#: many daily returns the sum actually covered -- a short window is visible in
#: ``window_days`` rather than silently reported as a year.
#:
#: The dividend is dropped from the return when it exceeds the prior close; the price
#: return is unaffected by that guard because it never included the dividend.
FORWARD_RETURN_SQL = """
WITH d AS (
  -- The per-payment series only. See the module docstring: adding the XBRL
  -- annual totals books every payment of a doubly-covered payer twice.
  SELECT security_id, ex_dividend_date,
         COALESCE(adjusted_amount, amount) AS amount
  FROM raw.dividend_data
  WHERE amount > 0 AND provider = 'OPENBB'
),
div_on_row AS (
  -- The first price row on or after the ex-date, not the row equal to it: an
  -- ex-date can fall on a day the price series has no row, and an equality join
  -- would drop the payment rather than move it.
  SELECT e.security_id, m.observation_date, SUM(e.amount) AS amount
  FROM d e
  CROSS JOIN LATERAL (
    SELECT observation_date FROM raw.market_data m
    WHERE m.security_id = e.security_id
      AND m.observation_date >= e.ex_dividend_date
      AND m.close IS NOT NULL
    ORDER BY m.observation_date
    LIMIT 1) m
  GROUP BY 1, 2
),
r AS (
  SELECT m.security_id, m.observation_date, m.close,
    LN(m.close / NULLIF(LAG(m.close) OVER w, 0)) AS daily_price_return,
    LN((m.close + CASE WHEN dv.amount <= :max_payment_ratio * LAG(m.close) OVER w
                       THEN dv.amount ELSE 0 END)
       / NULLIF(LAG(m.close) OVER w, 0)) AS daily_total_return
  FROM raw.market_data m
  LEFT JOIN div_on_row dv
    ON dv.security_id = m.security_id
   AND dv.observation_date = m.observation_date
  WHERE m.close IS NOT NULL
  WINDOW w AS (PARTITION BY m.security_id ORDER BY m.observation_date)
),
fwd AS (
  SELECT security_id,
    observation_date AS as_of_date,
    -- The date the window ends: the last observation inside it, which is a
    -- trading date rather than a calendar anniversary of the start.
    MAX(observation_date) OVER w AS forward_date,
    COUNT(daily_total_return) OVER w AS window_days,
    EXP(SUM(daily_total_return) OVER w) - 1 AS total_return,
    EXP(SUM(daily_price_return) OVER w) - 1 AS price_return
  FROM r
  WINDOW w AS (PARTITION BY security_id ORDER BY observation_date
               ROWS BETWEEN 1 FOLLOWING AND :window_days FOLLOWING)
)
SELECT security_id, as_of_date, forward_date, window_days,
  total_return, price_return,
  total_return - price_return AS dividend_return
FROM fwd
-- A window shorter than the horizon is not a year. The count is checked, not
-- assumed, because a partial sum is a valid number that means something else.
WHERE window_days = :window_days
  AND total_return IS NOT NULL
  AND as_of_date >= :date_from AND as_of_date < :date_to
"""


def build_forward_returns(date_from=None, date_to=None, window_days=FORWARD_WINDOW_DAYS):
    """Compute the forward returns for one observation-date window.

    The window bounds the output, not the calculation: the forward window of the last
    row in the window reaches 252 trading days past it, and those prices are read
    whatever the window is. A caller that asks for the whole history gets every
    complete window in it, which is every date whose 252nd following observation is
    also stored -- so the materialised range stops 252 trading days before the last
    stored price, and the gap is the lag in the data rather than a missing build.
    """
    params = {
        "date_from": date_from or date.min,
        "date_to": date_to or date.max,
        "max_payment_ratio": MAX_SINGLE_PAYMENT_RATIO,
        "window_days": window_days,
    }
    df = read_df(FORWARD_RETURN_SQL, params)
    if df.empty:
        return df
    df["window_days"] = df["window_days"].astype(int)
    for column in ("total_return", "price_return", "dividend_return"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.replace([np.inf, -np.inf], np.nan)


def forward_return_payload(df):
    """Return the forward-return rows as bind-parameter dicts, with NULLs for gaps."""
    records = df.to_dict(orient="records")
    return [
        {column: _db_value(record.get(column)) for column in FORWARD_COLUMNS} for record in records
    ]


def _db_value(value):
    """Map pandas missing values to SQL NULL.

    Postgres ``numeric`` stores NaN happily, but a stored NaN sorts above every
    other number and poisons AVG/MIN downstream, so missing data has to be written
    as a real NULL.
    """
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


INSERT_FORWARD_RETURN = text(
    """
INSERT INTO model.forward_returns (
    security_id, as_of_date, forward_date, window_days,
    total_return, price_return, dividend_return
)
VALUES (:security_id, :as_of_date, :forward_date, :window_days,
        :total_return, :price_return, :dividend_return)
ON CONFLICT(security_id, as_of_date) DO UPDATE SET
    forward_date = EXCLUDED.forward_date,
    window_days = EXCLUDED.window_days,
    total_return = EXCLUDED.total_return,
    price_return = EXCLUDED.price_return,
    dividend_return = EXCLUDED.dividend_return
"""
)


def persist_forward_returns(df, chunk_size=FORWARD_CHUNK_SIZE):
    """Write the forward returns, upserting on (security_id, as_of_date).

    The insert is an upsert so a rerun over any window is idempotent, which is what
    lets the nightly rebuild only the tail.
    """
    if df.empty:
        return 0
    written = 0
    for start in range(0, len(df), chunk_size):
        payload = forward_return_payload(df.iloc[start : start + chunk_size])
        with engine.begin() as conn:
            conn.execute(INSERT_FORWARD_RETURN, payload)
        written += len(payload)
    return written


def observation_date_range():
    """The first and last stored price dates, for the build to bound itself by."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT min(observation_date), max(observation_date) "
                "FROM raw.market_data WHERE close IS NOT NULL"
            )
        ).fetchone()
    return row


def observation_density(date_from, date_to):
    """The number of priced observations in a date range.

    The forward table holds at most one row per priced observation, so this is an
    upper bound on what a range can produce, and the density it implies is what
    the build uses to size its windows: the price scan behind a window costs the
    same whatever the window covers, so a window should be as wide as the memory
    it needs allows, not a fixed number of days.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT count(*) FROM raw.market_data "
                "WHERE close IS NOT NULL "
                "AND observation_date >= CAST(:d1 AS date) "
                "AND observation_date < CAST(:d2 AS date)"
            ),
            {"d1": date_from, "d2": date_to},
        ).fetchone()
    return int(row[0]) if row else 0


def forward_returns_for(security_id, as_of_date=None, limit=None, query=None):
    """The stored forward returns for one security, newest first.

    Read from the materialised table, so a caller pays nothing for the scan that
    built it. Takes the same ``(sql, params) -> frame`` callable as the rest of
    the read side, so a caller can inject the app's own query function.
    """
    sql = (
        "SELECT security_id, as_of_date, forward_date, window_days, "
        "total_return, price_return, dividend_return "
        "FROM model.forward_returns WHERE security_id = CAST(:sid AS uuid)"
    )
    params = {"sid": str(security_id)}
    if as_of_date is not None:
        sql += " AND as_of_date <= CAST(:as_of AS date)"
        params["as_of"] = as_of_date
    sql += " ORDER BY as_of_date DESC"
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = int(limit)
    return (query or read_df)(sql, params)
