"""Column definitions for hover help.

Every table and view in the warehouse carries a ``COMMENT ON COLUMN`` definition. This
module surfaces those definitions as hover tooltips so a reader can see what an attribute
means without leaving the page. The comments are read once from ``pg_catalog`` and cached;
a column with no comment shows no tooltip rather than an invented one.

Column names are not unique across the warehouse (``security_id``, ``provider``,
``currency`` ...), so a lookup is relation-scoped wherever the caller knows the relation.
A bare name resolves only when it means the same thing everywhere it appears; an
ambiguous name returns ``None`` instead of a possibly-wrong definition. A short curated
``note`` covers a label that is derived in SQL and therefore has no column of its own.
"""

from __future__ import annotations

import streamlit as st

from app import ui
from src.crispdm.scoring import WEIGHTS

_WEIGHT_LABELS = {
    "dividend_income_score": "Income",
    "sustainability_score": "Sustainability",
    "appreciation_score": "Appreciation",
    "risk_score": "Risk",
    "valuation_score": "Valuation",
}

#: One caption for every screen that states the composite weights, derived from
#: the scorer so a weight change cannot leave a stale percentage in the UI.
SCORING_CAPTION = " | ".join(
    f"{_WEIGHT_LABELS[name]} {weight:.1%}" for name, weight in WEIGHTS.items()
)

_SQL = """
SELECT n.nspname || '.' || c.relname AS relation,
       a.attname AS column_name,
       col_description(a.attrelid, a.attnum) AS comment
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0 AND NOT a.attisdropped
  AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public')
  AND col_description(a.attrelid, a.attnum) IS NOT NULL
"""


@st.cache_data(ttl=300, show_spinner=False)
def _comments() -> dict:
    """Read every column comment once.

    Returns ``by_relation["schema.table"][column]`` plus ``by_name[column]`` for the names
    that carry a single definition across the whole warehouse. A name used with more than
    one meaning is deliberately left out of ``by_name`` so a bare lookup cannot guess.
    """
    frame = ui.query(_SQL)
    by_relation: dict[str, dict[str, str]] = {}
    seen: dict[str, set[str]] = {}
    for relation, column, comment in frame.itertuples(index=False):
        by_relation.setdefault(relation, {})[column] = comment
        seen.setdefault(column, set()).add(comment)
    by_name = {column: next(iter(texts)) for column, texts in seen.items() if len(texts) == 1}
    return {"by_relation": by_relation, "by_name": by_name}


def comment(relation: str, column: str) -> str | None:
    """The ``COMMENT ON COLUMN`` text for one column of a known relation."""
    return _comments()["by_relation"].get(relation, {}).get(column)


def comment_any(column: str) -> str | None:
    """The comment for a column name that means the same thing everywhere, else None."""
    return _comments()["by_name"].get(column)


def help_text(
    *,
    relation: str | None = None,
    column: str | None = None,
    note: str | None = None,
) -> str | None:
    """The tooltip for one attribute: its stored definition, with a curated note appended.

    The stored definition wins when both are present, so the schema stays the source of
    truth and a note only sharpens it. A note stands alone for a label that is derived in
    SQL. Returns None when there is neither, so the caller can omit the tooltip.
    """
    base = None
    if column is not None:
        base = comment(relation, column) if relation else comment_any(column)
    if base:
        return f"{base}\n\n{note}" if note else base
    return note


def config_map(specs: dict, columns=None) -> dict:
    """``st.column_config`` entries from ``{column: (relation, source_column, note)}``.

    For a frame whose columns come from different relations, or are renamed in SQL. When
    ``columns`` is given, only those are kept so a config never names a column the frame
    does not have.
    """
    config = {}
    for column, (relation, source, note) in specs.items():
        if columns is not None and column not in columns:
            continue
        text = help_text(relation=relation, column=source, note=note)
        if text is not None:
            config[column] = st.column_config.Column(help=text)
    return config


def config_for(
    relation: str,
    columns,
    *,
    notes: dict[str, str] | None = None,
) -> dict:
    """``st.column_config`` entries carrying each column's definition as header help.

    For a frame read from a single relation. Columns with no comment and no note are left
    out, so they render with Streamlit's default header. ``notes`` covers a SQL-derived
    column whose name does not exist in the relation.
    """
    notes = notes or {}
    config = {}
    for column in columns:
        text = help_text(relation=relation, column=column, note=notes.get(column))
        if text is not None:
            config[column] = st.column_config.Column(help=text)
    return config


__all__ = ["comment", "comment_any", "config_for", "config_map", "help_text"]
