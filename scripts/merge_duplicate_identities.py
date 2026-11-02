"""Remove redundant duplicate identities of one ticker so the real one can be retyped in place.

``reference.securities`` is unique on ``(cik, ticker, security_type, dividend)``. A ticker
that stage 1 once typed two different ways keeps both rows: one active, one inactive twin,
and the stage-2 and stage-3 loaders populate prices, dividends and fundamentals for each.
When the active row's type later has to change to the twin's type, an in-place retype is
impossible (the twin holds the key), and stage 1 instead swaps the active flag to the twin,
stranding the scoring history that sits on the active row.

This tool deletes the twin when, and only when, it is redundant: every row of every
dependent table that belongs to the twin is content-identical to a row of the active
identity (compared ignoring ``security_id``, serial ids and load timestamps), and the twin
owns nothing in a table that cannot be compared that way. The twin's rows are archived to
JSON first, in one transaction. A twin with anything the active identity lacks is reported
and left alone.

Run over the 160 securities whose type the corrected title classifier would change, only 60
had a twin that differed from the active row in rebuilt tables alone. In 100 a twin held
history the active row lacked, and where both carried a price series for the same dates, the
values disagreed (LFMD, PBR, UMH, PW: about 1,900 differing rows each). Those need a decision
about which series is authoritative; this tool deliberately does not make it.

It reuses the foreign-key graph and archive format of ``scripts.resolve_ticker_conflict``.

    python -m scripts.merge_duplicate_identities --ticker RNXT            # report only
    python -m scripts.merge_duplicate_identities --ticker RNXT --execute --confirm RNXT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts.resolve_ticker_conflict import dependent_graph, doomed_predicate, foreign_keys
from scripts.run_full_etl import PipelineAlreadyRunning, _acquire_run_lock, _release_run_lock
from src.crispdm.db import engine

ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "data" / "ticker_conflict_archive"
ROOT = "reference.securities"

#: Per-security metadata the nightly rebuilds from the security's type and name. Two identities
#: typed differently differ here by construction, and it holds no history: a difference is
#: reported (and archived with the twin) but does not make a twin non-redundant. Everything
#: else, prices, dividends, fundamentals, features, scores, predictions and so on, must match.
REBUILT_TABLES = frozenset(
    {
        "raw.ticker_profile",
        "clean.ticker_profile",
        "preferred.security_terms",
        "audit.data_quality",  # regenerated each night by populate_audit
        "clean.company_profile",
        "clean.company_officer",
    }
)


def ignored_columns(conn, table: str) -> list[str]:
    """Columns that legitimately differ between two copies of the same data.

    ``security_id`` itself, serial/identity ids, and load/refresh timestamps.
    """
    schema, name = table.split(".")
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, column_default, is_identity FROM "
            "information_schema.columns WHERE table_schema = :s AND table_name = :t"
        ),
        {"s": schema, "t": name},
    ).mappings()
    out = []
    for r in rows:
        col = r["column_name"]
        default = r["column_default"] or ""
        if (
            col == "security_id"
            or r["is_identity"] == "YES"
            or "nextval" in default
            or (r["data_type"].startswith("timestamp") and col.endswith("_at"))
        ):
            out.append(col)
    return out


def has_column(conn, table: str, column: str) -> bool:
    schema, name = table.split(".")
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = :s "
                "AND table_name = :t AND column_name = :c"
            ),
            {"s": schema, "t": name, "c": column},
        ).scalar()
    )


def unmatched_twin_rows(conn, table: str, twin, active) -> int:
    """Rows of ``twin`` in ``table`` with no content-identical row on ``active``."""
    strip = " ".join(f"- '{col}'" for col in ignored_columns(conn, table))
    return conn.execute(
        text(
            f"SELECT count(*) FROM {table} tw WHERE tw.security_id = :twin AND NOT EXISTS ("  # noqa: S608
            f"SELECT 1 FROM {table} a WHERE a.security_id = :active "
            f"AND (to_jsonb(a) {strip}) = (to_jsonb(tw) {strip}))"
        ),
        {"twin": twin, "active": active},
    ).scalar()


def twin_rows(conn, table: str, predicate: str, twin) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {table} t WHERE {predicate}"),  # noqa: S608
        {"sids": [str(twin)]},
    ).scalar()


def assess_twin(conn, twin, active, plan_tables) -> dict:
    """Is ``twin`` redundant against ``active``? Returns the evidence either way."""
    findings, blockers, deleted, rebuilt_differs = {}, [], {}, {}
    for item in plan_tables:
        table = item["table"]
        count = twin_rows(conn, table, item["predicate"], twin)
        if table == ROOT:
            deleted[table] = count
            continue
        if count == 0:
            continue
        deleted[table] = count
        if has_column(conn, table, "security_id"):
            missing = unmatched_twin_rows(conn, table, twin, active)
            findings[table] = {"twin_rows": count, "not_on_active": missing}
            if missing and table in REBUILT_TABLES:
                rebuilt_differs[table] = missing
            elif missing:
                blockers.append(
                    f"{table}: {missing} of {count} twin rows are not on the active row"
                )
        else:
            findings[table] = {"twin_rows": count, "comparable": False}
            blockers.append(f"{table}: {count} twin rows reached only through another table")
    return {
        "redundant": not blockers,
        "blockers": blockers,
        "rebuilt_metadata_differs": rebuilt_differs,
        "findings": findings,
        "rows": deleted,
    }


def plan_for(conn):
    order, edges = dependent_graph(foreign_keys(conn))
    return [{"table": t, "predicate": doomed_predicate(t, edges)} for t in order]


def identities(conn, ticker: str):
    rows = (
        conn.execute(
            text(
                "SELECT security_id, security_type, active, dividend, cik FROM reference.securities "
                "WHERE ticker = :t ORDER BY active DESC, security_type"
            ),
            {"t": ticker},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def report(conn, ticker: str) -> dict:
    ids = identities(conn, ticker)
    active = [r for r in ids if r["active"]]
    if len(active) != 1:
        return {"ticker": ticker, "error": f"expected one active identity, found {len(active)}"}
    plan = plan_for(conn)
    twins = []
    for twin in (r for r in ids if not r["active"]):
        if twin["cik"] != active[0]["cik"]:
            continue
        verdict = assess_twin(conn, twin["security_id"], active[0]["security_id"], plan)
        twins.append(
            {"security_id": str(twin["security_id"]), "type": twin["security_type"], **verdict}
        )
    return {
        "ticker": ticker,
        "active": {
            "security_id": str(active[0]["security_id"]),
            "type": active[0]["security_type"],
        },
        "twins": twins,
        "all_redundant": bool(twins) and all(t["redundant"] for t in twins),
    }


def delete_twins(conn, ticker: str, archive_path: Path | None) -> dict:
    """Archive then delete every redundant twin of ``ticker``. Caller owns the transaction."""
    rep = report(conn, ticker)
    if "error" in rep or not rep["all_redundant"]:
        raise RuntimeError(f"{ticker}: not every twin is redundant; nothing deleted")
    plan = plan_for(conn)
    sids = [t["security_id"] for t in rep["twins"]]
    if archive_path is not None:
        body = {
            "ticker": ticker,
            "twins": sids,
            "active": rep["active"],
            "evidence": rep["twins"],
            "rows": {},
        }
        for item in plan:
            rows = conn.execute(
                text(f"SELECT to_jsonb(t) FROM {item['table']} t WHERE {item['predicate']}"),  # noqa: S608
                {"sids": sids},
            ).scalars()
            data = list(rows)
            if data:
                body["rows"][item["table"]] = data
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with open(archive_path, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=1, default=str)
            handle.flush()
            os.fsync(handle.fileno())
    deleted = {}
    for item in plan:  # children first, root last
        n = conn.execute(
            text(f"DELETE FROM {item['table']} t WHERE {item['predicate']}"),  # noqa: S608
            {"sids": sids},
        ).rowcount
        if n:
            deleted[item["table"]] = n
    left = conn.execute(
        text("SELECT count(*) FROM reference.securities WHERE security_id::text = ANY(:s)"),
        {"s": sids},
    ).scalar()
    if left:
        raise RuntimeError(f"{ticker}: a twin is still present after the delete")
    return {"ticker": ticker, "twins_deleted": sids, "rows_deleted": deleted}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    ticker = args.ticker.strip().upper()
    if args.execute and args.confirm != ticker:
        print(f"--execute requires --confirm {ticker}", file=sys.stderr)
        return 2
    lock = None
    if args.execute:
        try:
            lock = _acquire_run_lock()
        except PipelineAlreadyRunning as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    try:
        with engine.connect() as conn:
            if not args.execute:
                print(json.dumps(report(conn, ticker), indent=2, default=str))
                return 0
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = ARCHIVE_DIR / f"twins_{ticker}_{stamp}.json"
            with conn.begin():
                result = delete_twins(conn, ticker, archive)
            print(json.dumps({**result, "archive": str(archive)}, indent=2, default=str))
            return 0
    finally:
        if lock is not None:
            _release_run_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
