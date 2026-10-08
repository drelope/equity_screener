"""A safe table browser: pick a dataset, filter, sort, limit.

User input reaches SQL in exactly three places, and each is closed:

* The relation must be one of ``DATASETS``. It is never taken from input.
* Column names (select, filter, order) must be in the reflected column set of that
  relation, and are then double-quoted.
* Operators come from ``OPERATORS``. Values are bound parameters, coerced to the
  column's type first, so a value can never be parsed as SQL.

Queries run in a read-only transaction with a statement timeout and a row cap, so the
explorer cannot modify data or tie up the warehouse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import text

MAX_ROWS = 5000
DEFAULT_ROWS = 500
STATEMENT_TIMEOUT = "15s"
MAX_FILTERS = 8


@dataclass(frozen=True)
class Dataset:
    label: str
    relation: str
    description: str
    default_order: str | None = None


DATASETS: dict[str, Dataset] = {
    d.label: d
    for d in (
        Dataset(
            "Securities",
            "reference.securities",
            "Every instrument the pipeline knows, with its classification and flags.",
            "ticker",
        ),
        Dataset(
            "Current predictions",
            "model.current_predictions",
            "The latest prediction per security.",
            None,
        ),
        Dataset("Scores", "model.scores", "Composite and component scores by date.", "as_of_date"),
        Dataset("Rankings", "model.rankings", "Ranked securities by date.", "as_of_date"),
        Dataset(
            "Dividends",
            "raw.dividend_data",
            "Dividend events from OpenBB and SEC XBRL.",
            "ex_dividend_date",
        ),
        Dataset(
            "Fundamentals",
            "fundamentals.periodic_financials",
            "Reported figures, one row per period and filing.",
            "period_end",
        ),
        Dataset(
            "Preferred terms",
            "preferred.security_terms",
            "Coupon and liquidation terms mined for preferred shares.",
            None,
        ),
        Dataset(
            "Clean ticker profile",
            "clean.ticker_profile",
            "One normalised profile row per security.",
            "ticker",
        ),
        Dataset("Data quality", "audit.data_quality", "Per-security quality scores.", "as_of_date"),
        Dataset(
            "Quarantined values",
            "audit.quarantined_values",
            "Known-wrong values left in place and recorded.",
            "quarantine_id",
        ),
        Dataset("Nightly runs", "audit.nightly_runs", "One row per ETL execution.", "run_id"),
        Dataset(
            "Nightly checks",
            "audit.nightly_checks",
            "Recorded morning verifications.",
            "verified_at",
        ),
    )
}

OPERATORS = {
    "=": "=",
    "!=": "<>",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "contains": "ILIKE",
    "is empty": "IS NULL",
    "is not empty": "IS NOT NULL",
}

_NUMBER = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
_DATE = {"date"}
_TIMESTAMP = {"timestamp with time zone", "timestamp without time zone"}
_BOOL = {"boolean"}
_TEXT = {"text", "character varying", "character", "uuid", "name"}

#: Which operators make sense for which kind of column.
OPERATORS_BY_KIND = {
    "number": ["=", "!=", ">", ">=", "<", "<=", "is empty", "is not empty"],
    "date": ["=", "!=", ">", ">=", "<", "<=", "is empty", "is not empty"],
    "text": ["=", "!=", "contains", "is empty", "is not empty"],
    "bool": ["=", "!=", "is empty", "is not empty"],
    "other": ["is empty", "is not empty"],
}


def kind_of(data_type: str) -> str:
    if data_type in _NUMBER:
        return "number"
    if data_type in _DATE or data_type in _TIMESTAMP:
        return "date"
    if data_type in _BOOL:
        return "bool"
    if data_type in _TEXT:
        return "text"
    return "other"


def dataset(label: str) -> Dataset:
    try:
        return DATASETS[label]
    except KeyError:
        raise ValueError(f"unknown dataset {label!r}") from None


def reflect_columns(conn, relation: str) -> dict[str, str]:
    """Column name -> data type for an allowlisted relation, in table order."""
    if relation not in {d.relation for d in DATASETS.values()}:
        raise ValueError(f"{relation!r} is not an explorable dataset")
    schema, _, table = relation.partition(".")
    rows = conn.execute(
        text("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position
    """),
        {"s": schema, "t": table},
    ).all()
    return {name: dtype for name, dtype in rows}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_relation(relation: str) -> str:
    return ".".join(_quote(part) for part in relation.split("."))


def _coerce(value: Any, kind: str, column: str) -> Any:
    if kind == "number":
        try:
            number = float(str(value).replace(",", "").strip())
        except ValueError:
            raise ValueError(f"{column}: {value!r} is not a number") from None
        if not math.isfinite(number):
            raise ValueError(f"{column}: {value!r} is not a finite number")
        return number
    if kind == "date":
        text_value = str(value).strip()
        try:
            return (
                datetime.fromisoformat(text_value)
                if "T" in text_value or " " in text_value
                else date.fromisoformat(text_value)
            )
        except ValueError:
            raise ValueError(f"{column}: {value!r} is not a YYYY-MM-DD date") from None
    if kind == "bool":
        lowered = str(value).strip().lower()
        if lowered in ("true", "t", "yes", "y", "1"):
            return True
        if lowered in ("false", "f", "no", "n", "0"):
            return False
        raise ValueError(f"{column}: {value!r} is not true/false")
    return str(value)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_query(
    relation: str,
    columns: dict[str, str],
    *,
    select: list[str] | None = None,
    filters: list[dict] | None = None,
    order_by: str | None = None,
    descending: bool = False,
    limit: int = DEFAULT_ROWS,
) -> tuple[str, dict]:
    """Return ``(sql, params)`` for one browse; raises ValueError on anything invalid."""
    if relation not in {d.relation for d in DATASETS.values()}:
        raise ValueError(f"{relation!r} is not an explorable dataset")

    chosen = list(select or columns)
    unknown = [c for c in chosen if c not in columns]
    if unknown:
        raise ValueError(f"unknown column(s): {', '.join(map(str, unknown))}")
    if not chosen:
        raise ValueError("select at least one column")

    clauses: list[str] = []
    params: dict[str, Any] = {}
    filters = filters or []
    if len(filters) > MAX_FILTERS:
        raise ValueError(f"at most {MAX_FILTERS} filters")
    for index, flt in enumerate(filters):
        column, op = flt.get("column"), flt.get("op")
        if column not in columns:
            raise ValueError(f"unknown filter column {column!r}")
        if op not in OPERATORS:
            raise ValueError(f"unknown operator {op!r}")
        kind = kind_of(columns[column])
        if op not in OPERATORS_BY_KIND[kind]:
            raise ValueError(f"{op!r} cannot be used on {kind} column {column!r}")
        ident = _quote(column)
        if op in ("is empty", "is not empty"):
            clauses.append(f"{ident} {OPERATORS[op]}")
            continue
        raw = flt.get("value")
        if raw is None or str(raw).strip() == "":
            raise ValueError(f"filter on {column!r} needs a value")
        name = f"v{index}"
        if op == "contains":
            clauses.append(f"{ident} ILIKE :{name} ESCAPE '\\'")
            params[name] = f"%{_escape_like(str(raw))}%"
        else:
            clauses.append(f"{ident} {OPERATORS[op]} :{name}")
            params[name] = _coerce(raw, kind, column)

    sql = f"SELECT {', '.join(_quote(c) for c in chosen)} FROM {_quote_relation(relation)}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by is not None:
        if order_by not in columns:
            raise ValueError(f"unknown sort column {order_by!r}")
        sql += f" ORDER BY {_quote(order_by)} {'DESC' if descending else 'ASC'} NULLS LAST"
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be a whole number")
    sql += f" LIMIT {max(1, min(limit, MAX_ROWS))}"
    return sql, params


def run_query(engine, sql: str, params: dict) -> pd.DataFrame:
    """Execute in a read-only transaction with a statement timeout."""
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            return pd.read_sql(text(sql), conn, params=params)
