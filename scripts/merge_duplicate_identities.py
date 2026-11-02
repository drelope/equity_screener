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

``--merge`` is for a twin that holds history the active identity lacks: where both identities
have a row for the same key the active one is kept (provided the twin's is the same data, see
``overlap_guard``), and rows only the twin has move to the active identity.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
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

#: Tables computed from the history tables (prices, dividends, fundamentals) or caches of
#: documents. A twin's rows here that the active identity lacks are rebuildable from the
#: active identity's own history, so they do not block a delete, but only because every
#: history table is required to be redundant first: if a history table blocks, these are moot.
#: Model OUTPUTS (scores, predictions, rankings) are not in this set: a past score was computed
#: with the data of its day and cannot be regenerated, so it must be on the active identity.
DERIVED_TABLES = frozenset(
    {
        "model.features",
        "model.forward_returns",
        "preferred.dividend_snapshot",
        "raw.contract_documents",
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
            if missing and (table in REBUILT_TABLES or table in DERIVED_TABLES):
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


#: Date column of the dated history/derived tables, for ``--skip-move-before``.
DATE_COLUMN = {
    "raw.market_data": "observation_date",
    "model.features": "as_of_date",
    "model.forward_returns": "as_of_date",
}
#: Tables whose twin-only rows move to the active identity. Rebuilt metadata is not moved: it
#: describes the twin's type and is regenerated for the active row.
MOVE_TABLES = (
    "raw.market_data",
    "fundamentals.periodic_financials",
    "raw.dividend_data",
    "raw.corporate_actions",
    "model.features",
    "model.forward_returns",
)
#: Columns that name which source supplied a row, not what it says (a dividend's ``feed`` is
#: 'fmp' on the active row and 'yfinance' on an older twin). They are not compared.
PROVENANCE_COLUMNS = frozenset({"feed", "amount_feed"})

#: An overlapping bar's close may differ by this much and still be "the same bar". The close is
#: what the models use. Volume is revised after the fact, and a stray open/high/low tick (PW,
#: 2024-06-03: one bar's high 15.8 against 11.8 with identical close and volume) is not a
#: different price series, so neither is compared.
MAX_PRICE_DEVIATION = 0.02


HISTORY_TABLES = (
    "raw.market_data",
    "raw.dividend_data",
    "raw.corporate_actions",
    "fundamentals.periodic_financials",
    "model.features",
    "model.scores",
    "model.predictions",
    "model.rankings",
    "model.forward_returns",
)


def history_counts(conn, security_id) -> dict[str, int]:
    return {
        t: conn.execute(
            text(f"SELECT count(*) FROM {t} WHERE security_id = :s"),  # noqa: S608
            {"s": security_id},
        ).scalar()
        for t in HISTORY_TABLES
    }


def primary_key_columns(conn, table: str) -> list[str]:
    """Primary-key columns of ``table`` other than ``security_id``."""
    rows = conn.execute(
        text(
            "SELECT a.attname FROM pg_constraint c "
            "CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(n, o) "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.n "
            "WHERE c.contype = 'p' AND c.conrelid = CAST(:t AS regclass) ORDER BY k.o"
        ),
        {"t": table},
    ).scalars()
    return [c for c in rows if c != "security_id"]


def overlap_guard(conn, table: str, twin, active) -> str | None:
    """None if the rows both identities hold for the same key are the same data, else why not.

    Policy, from the 19 securities this was written for: where both exist the active identity
    is authoritative, but only if the twin's version is the same data. Prices may differ by a
    rounding or snapshot margin; a fundamentals field may be NULL on the twin (older extractor)
    but never the other way round or a different value.
    """
    cols = primary_key_columns(conn, table)
    if not cols or table in DERIVED_TABLES:
        # A derived row (features, forward returns) is computed from the history tables, so
        # it differs wherever their inputs differ; the active identity's is computed from
        # the authoritative inputs and wins without a guard of its own.
        return None
    join = " AND ".join(f"a.{c} = tw.{c}" for c in cols)
    if table == "raw.market_data":
        n = conn.execute(
            text(
                f"SELECT count(*) FROM {table} tw JOIN {table} a ON {join} AND a.security_id = :a "  # noqa: S608
                "WHERE tw.security_id = :t AND ("
                + f"abs(tw.close / nullif(a.close, 0) - 1) > {MAX_PRICE_DEVIATION}"
                + ")"
            ),
            {"a": active, "t": twin},
        ).scalar()
        return (
            f"{n} overlapping closes differ by more than {MAX_PRICE_DEVIATION:.0%}" if n else None
        )
    # Every other history table (fundamentals, dividends, corporate actions): the twin may hold
    # NULL where the active row has a value (an older extractor), never a different value.
    schema, name = table.split(".")
    columns = [
        c
        for c in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": schema, "t": name},
        ).scalars()
        if c not in cols and c not in ignored_columns(conn, table) and c not in PROVENANCE_COLUMNS
    ]
    bad = " OR ".join(f"(tw.{c} IS NOT NULL AND tw.{c} IS DISTINCT FROM a.{c})" for c in columns)
    if not bad:
        return None
    n = conn.execute(
        text(
            f"SELECT count(*) FROM {table} tw JOIN {table} a ON {join} AND a.security_id = :a "  # noqa: S608
            f"WHERE tw.security_id = :t AND ({bad})"
        ),
        {"a": active, "t": twin},
    ).scalar()
    return (
        f"{n} overlapping rows hold a twin value the active row lacks or contradicts" if n else None
    )


def move_twin_rows(conn, twin, active, skip_before=None) -> dict[str, int]:
    """Re-point the twin's rows whose key the active identity lacks. Returns rows moved."""
    moved = {}
    for table in MOVE_TABLES:
        cols = primary_key_columns(conn, table)
        if not cols or not has_column(conn, table, "security_id"):
            continue
        refusal = overlap_guard(conn, table, twin, active)
        if refusal:
            raise RuntimeError(f"{table}: {refusal}")
        key = " AND ".join(f"a.{c} = {table.split('.')[1]}.{c}" for c in cols)
        extra = ""
        params = {"a": active, "t": twin}
        if skip_before and table in DATE_COLUMN:
            extra = f" AND {DATE_COLUMN[table]} >= :skip"
            params["skip"] = skip_before
        n = conn.execute(
            text(
                f"UPDATE {table} SET security_id = :a WHERE security_id = :t{extra} "  # noqa: S608
                f"AND NOT EXISTS (SELECT 1 FROM {table} a WHERE a.security_id = :a AND {key})"
            ),
            params,
        ).rowcount
        if n:
            moved[table] = n
    return moved


def merge_twins(conn, ticker: str, archive_path: Path | None, skip_before=None) -> dict:
    """Archive, move the twins' unique history to the active identity, delete the twins.

    Caller owns the transaction. Refuses (raising) if an overlapping row is not the same data.
    """
    rep = report(conn, ticker)
    if "error" in rep:
        raise RuntimeError(f"{ticker}: {rep['error']}")
    active = rep["active"]["security_id"]
    sids = [t["security_id"] for t in rep["twins"]]
    plan = plan_for(conn)
    if archive_path is not None:
        body = {"ticker": ticker, "twins": sids, "active": rep["active"], "rows": {}}
        for item in plan:
            data = list(
                conn.execute(
                    text(f"SELECT to_jsonb(t) FROM {item['table']} t WHERE {item['predicate']}"),  # noqa: S608
                    {"sids": sids},
                ).scalars()
            )
            if data:
                body["rows"][item["table"]] = data
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with open(archive_path, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=1, default=str)
            handle.flush()
            os.fsync(handle.fileno())
    before = history_counts(conn, active)
    moved = {}
    for twin in sids:
        for table, n in move_twin_rows(conn, twin, active, skip_before).items():
            moved[table] = moved.get(table, 0) + n
    # Whatever remains on the twins is overlap (already guarded) or skipped-by-request history.
    deleted = {}
    for item in plan:
        n = conn.execute(
            text(f"DELETE FROM {item['table']} t WHERE {item['predicate']}"),  # noqa: S608
            {"sids": sids},
        ).rowcount
        if n:
            deleted[item["table"]] = n
    after = history_counts(conn, active)
    grew = {t: after[t] - before[t] for t in after if after[t] != before[t]}
    expected = {t: n for t, n in moved.items() if t in after}
    if grew != expected:
        raise RuntimeError(
            f"{ticker}: the active identity's row counts changed by {grew}, expected {expected}"
        )
    return {"ticker": ticker, "twins_deleted": sids, "rows_moved": moved, "rows_deleted": deleted}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Move the twins' unique history to the active identity, then delete the twins.\n"
        "Without --execute the whole merge is performed and rolled back.",
    )
    parser.add_argument(
        "--skip-move-before",
        type=date.fromisoformat,
        help="With --merge: twin prices/features/forward returns dated before this are not moved\n"
        "(they stay in the archive only), e.g. a different company's earlier history.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    ticker = args.ticker.strip().upper()
    if args.execute and args.confirm != ticker:
        print(f"--execute requires --confirm {ticker}", file=sys.stderr)
        return 2
    if args.skip_move_before and not args.merge:
        print("--skip-move-before needs --merge", file=sys.stderr)
        return 2
    lock = None
    if args.execute or args.merge:
        try:
            lock = _acquire_run_lock()
        except PipelineAlreadyRunning as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    try:
        with engine.connect() as conn:
            if not args.execute and not args.merge:
                print(json.dumps(report(conn, ticker), indent=2, default=str))
                return 0
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = ARCHIVE_DIR / f"twins_{ticker}_{stamp}.json" if args.execute else None
            transaction = conn.begin()
            try:
                if args.merge:
                    result = merge_twins(conn, ticker, archive, args.skip_move_before)
                else:
                    result = delete_twins(conn, ticker, archive)
            except Exception as exc:
                transaction.rollback()
                print(f"refused, nothing changed: {exc}", file=sys.stderr)
                return 1
            if args.execute:
                transaction.commit()
            else:
                transaction.rollback()
            mode = "EXECUTED" if args.execute else "DRY RUN (performed, then rolled back)"
            print(
                json.dumps(
                    {"mode": mode, **result, "archive": str(archive) if archive else None},
                    indent=2,
                    default=str,
                )
            )
            return 0
    finally:
        if lock is not None:
            _release_run_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
