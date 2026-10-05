"""Canonical description of a database's schema, for drift detection.

`scripts/migrate.py --check` compares the ``schema_migrations`` ledger against the
migrations on disk. That is a check on the *ledger*, not on the database: it cannot
see an object that was altered or dropped outside the migration runner, and it will
not re-apply a migration to repair one. During an audit a view was replaced with an
older definition and `--check` still reported "schema is up to date".

This module closes that gap the only way that is actually trustworthy -- by
comparing the live catalog against a database built from the repository. Not
against a checked-in expectation, because an expectation file drifts too; a build
either reproduces the schema or it does not.

The fingerprint is deliberately plain text. PostgreSQL exposes canonical
definitions for indexes, constraints and views via ``pg_get_*def``, so the output
is stable across dumps and diffable by eye when the check fails. Only objects the
project owns are included; ``pg_stat_statements`` and other extension-owned
objects exist in the live database and in no reference build.
"""

from __future__ import annotations

import re

from sqlalchemy import text

# Schemas whose contents are PostgreSQL's business, not the project's.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

# Objects the reference build legitimately lacks. The ledger table is created by
# the migration runner rather than by schema.sql, so it is created on both sides
# before fingerprinting and listed here only for callers that skip that step.
IGNORED_OBJECTS = {("public", "schema_migrations")}

_NOT_OURS = (
    "ns.nspname NOT IN ('pg_catalog','information_schema') AND ns.nspname NOT LIKE 'pg_toast%'"
)

_RELATION_KIND = {"r": "table", "p": "table", "v": "view", "m": "view"}


def fingerprint(conn, *, ignore=IGNORED_OBJECTS) -> dict[str, str]:
    """Return a comparable mapping of every project-owned schema object.

    Keys are prefixed by object type so a view and a table of the same name cannot
    collide, and values are PostgreSQL's own canonical definitions.
    """
    ignored = set(ignore)
    result: dict[str, str] = {}

    for schema, name, kind in conn.execute(
        text(
            f"""
            SELECT ns.nspname, c.relname, c.relkind
            FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
            WHERE c.relkind IN ('r','p','v','m')
              AND {_NOT_OURS}
              AND NOT c.relispartition
            ORDER BY 1,2
            """
        )
    ).all():
        result[f"relation {schema}.{name}"] = _RELATION_KIND[kind]

    for schema, table, column, ctype, nullable, default in conn.execute(
        text(
            f"""
            SELECT ns.nspname, cls.relname, att.attname,
                   format_type(att.atttypid, att.atttypmod),
                   CASE WHEN att.attnotnull THEN 'NO' ELSE 'YES' END,
                   pg_get_expr(def.adbin, def.adrelid)
            FROM pg_attribute att
            JOIN pg_class cls ON cls.oid = att.attrelid
            JOIN pg_namespace ns ON ns.oid = cls.relnamespace
            LEFT JOIN pg_attrdef def ON def.adrelid = att.attrelid
                                 AND def.adnum = att.attnum
            WHERE att.attnum > 0 AND NOT att.attisdropped
              AND cls.relkind IN ('r','p','v','m')
              AND {_NOT_OURS}
              AND NOT cls.relispartition
            ORDER BY 1,2, att.attnum
            """
        )
    ).all():
        result[f"column {schema}.{table}.{column}"] = (
            f"{ctype} null={nullable} default={default or ''}"
        )

    for schema, name, definition in conn.execute(
        text(
            f"""
            SELECT ns.nspname, cls.relname, pg_get_indexdef(i.indexrelid)
            FROM pg_index i
            JOIN pg_class cls ON cls.oid = i.indexrelid
            JOIN pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE {_NOT_OURS}
            ORDER BY 1,2
            """
        )
    ).all():
        result[f"index {schema}.{name}"] = definition

    # Keyed by constraint name, not table: a table has a primary key, foreign keys
    # and checks at once, so keying on the table collapses them onto one key and
    # whichever row the scan happened to return last wins.
    for schema, name, table, definition in conn.execute(
        text(
            f"""
            SELECT ns.nspname, con.conname, tbl.relname, pg_get_constraintdef(con.oid, true)
            FROM pg_constraint con
            JOIN pg_class tbl ON tbl.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = con.connamespace
            WHERE {_NOT_OURS}
            ORDER BY 1,2
            """
        )
    ).all():
        result[f"constraint {schema}.{name}"] = f"ON {schema}.{table} {definition}"

    for schema, name, definition in conn.execute(
        text(
            f"""
            SELECT ns.nspname, cls.relname, pg_get_viewdef(cls.oid, true)
            FROM pg_class cls JOIN pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE cls.relkind='v' AND {_NOT_OURS} ORDER BY 1,2
            """
        )
    ).all():
        result[f"viewdef {schema}.{name}"] = definition

    for schema, name, definition in conn.execute(
        text(
            f"""
            SELECT ns.nspname, t.typname,
                   COALESCE(bt.typname || ' ' || e.enumlabel, '')
            FROM pg_type t
            JOIN pg_namespace ns ON ns.oid = t.typnamespace
            LEFT JOIN pg_enum e ON e.enumtypid = t.oid
            LEFT JOIN pg_type bt ON bt.oid = e.enumtypid
            WHERE t.typtype='e' AND {_NOT_OURS}
            ORDER BY 1,2
            """
        )
    ).all():
        result[f"enum {schema}.{name}"] = definition

    for schema, name, oid in conn.execute(
        text(
            f"""
            SELECT ns.nspname, p.proname, p.oid
            FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace
            WHERE {_NOT_OURS} ORDER BY 1,2
            """
        )
    ).all():
        result[f"function {schema}.{name}"] = conn.execute(
            text("SELECT pg_get_functiondef(:oid)"), {"oid": oid}
        ).scalar()

    return {k: v for k, v in result.items() if not _is_ignored(k, ignored)}


_KEY = re.compile(
    r"^(?:column |index |constraint |viewdef |enum |function |relation )?([\w]+)\.([\w]+)"
)


def _is_ignored(key: str, ignored: set[tuple[str, str]]) -> bool:
    """Match an object against the ignore list, including columns of ignored tables.

    A column's key is ``column schema.table.column``, so a bare two-part match
    would miss ``public.schema_migrations.version``.
    """
    match = _KEY.match(key)
    if not match:
        return False
    schema, name = match.group(1), match.group(2)
    return (schema, name) in ignored or (schema, name.split(".")[0]) in ignored


def diff(
    live: dict[str, str], reference: dict[str, str]
) -> list[tuple[str, str, str | None, str | None]]:
    """Objects present in one fingerprint but not the other, or defined differently.

    Returned as ``(status, key, live_value, reference_value)`` where status is one
    of ``missing_from_live``, ``missing_from_reference`` or ``differs``.
    """
    out = []
    for key in sorted(set(live) - set(reference)):
        out.append(("missing_from_reference", key, live[key], None))
    for key in sorted(set(reference) - set(live)):
        out.append(("missing_from_live", key, None, reference[key]))
    for key in sorted(set(live) & set(reference)):
        if live[key] != reference[key]:
            out.append(("differs", key, live[key], reference[key]))
    return out


def format_report(problems, *, limit: int = 40) -> str:
    """Human-readable diff, ordered so the most structural problems come first."""
    if not problems:
        return "no drift"

    rank = {"missing_from_live": 0, "differs": 1, "missing_from_reference": 2}
    lines = []
    shown = sorted(problems, key=lambda p: (rank[p[0]], p[1]))
    for status, key, live_value, reference_value in shown[:limit]:
        lines.append(f"  {status}: {key}")
        if status == "differs":
            lines.append(f"      live:       {oneline(live_value)}")
            lines.append(f"      reference:  {oneline(reference_value)}")
        elif status == "missing_from_live":
            lines.append(f"      reference:  {oneline(reference_value)}")
        else:
            lines.append(f"      live:       {oneline(live_value)}")

    if len(shown) > limit:
        lines.append(f"  ... and {len(shown) - limit} more")
    counts = {}
    for status, *_ in shown:
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{counts[s]} {s}" for s in sorted(counts))
    return f"{len(problems)} difference(s): {summary}\n" + "\n".join(lines)


def oneline(value, width: int = 160):
    if value is None:
        return "<absent>"
    flat = " ".join(str(value).split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."
