"""Decide, and if warranted resolve, a TICKER_CIK_CONFLICT.

``populate_raw_tables`` skips a ticker that SEC now assigns to a different CIK than
the one a ``reference.securities`` row still references. It decides nothing about who
owns the ticker. This tool is where that decision is made.

Two commands, deliberately separate:

``review``  Read-only. Re-derives the open conflicts the way the stage does, gathers
            evidence from SEC's own per-issuer submissions, and classifies each one:

            STALE            SEC lists the ticker under the incoming CIK and no longer
                             under the existing one.
            INCOMING_WRONG   SEC still lists it under the existing CIK and not under the
                             incoming one.
            AMBIGUOUS        Anything else (both list it, neither does, or an issuer's
                             submissions are unavailable). Nothing is changed.

``release`` Only for a ticker whose existing mapping is to be retired. Dry-run unless
            ``--execute --confirm TICKER`` is given. It removes the stale
            ``reference.securities`` row and everything that hangs off it, after
            archiving every row to a JSON file, in one transaction.

Why release removes rather than deactivates: ``populate_securities`` sets
``active = TRUE`` for every ``raw.company_ticker`` row on every run, and
``fk_securities_company_ticker`` keeps referencing a row whether it is active or not.
An inactive row therefore never lets ``raw.company_ticker`` change its CIK, and no
re-key is possible because the key is ``(ticker, cik)`` and ``company_ticker`` holds
one CIK per ticker. Removal is the only thing that releases the ticker, so it is
gated, archived and recorded.

``release`` stops there. It does not touch ``raw.company_ticker``: the next ordinary
run of ``populate_raw_tables`` finds the ticker unreferenced and ingests the incoming
CIK with no override.

Usage:
    python -m scripts.resolve_ticker_conflict review [--ticker T] [--stored-only] [--json]
    python -m scripts.resolve_ticker_conflict release --ticker T --reviewed-by NAME
    python -m scripts.resolve_ticker_conflict release --ticker T --reviewed-by NAME \\
        --execute --confirm T [--basis "evidence the review could not establish"]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow direct execution from the repository root as well as `python -m`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts import populate_raw_tables as prt
from scripts.run_full_etl import PipelineAlreadyRunning, _acquire_run_lock, _release_run_lock
from src.crispdm.db import engine
from src.crispdm.sec_client import get_company_tickers, get_submissions

STALE = "STALE"
INCOMING_WRONG = "INCOMING_WRONG"
AMBIGUOUS = "AMBIGUOUS"

ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "data" / "ticker_conflict_archive"

#: audit.quarantined_values.ticker is VARCHAR(16); the full ticker is kept in
#: observed_value, so a longer one is truncated here rather than failing the release.
REGISTRY_TICKER_WIDTH = 16

ROOT_TABLE = "reference.securities"
ROOT_KEY = "security_id"


# --- the decision ----------------------------------------------------------------


def lists_ticker(submissions, ticker):
    """True/False if an issuer's submissions say it lists ``ticker``; None if unknown.

    An empty ticker list is unknown, not "lists nothing": SEC leaves it empty for a
    registrant it has not yet populated (Southport II on the day its units began
    trading), and reading that as absence called a correct mapping wrong.
    """
    listed = {str(t).strip().upper() for t in (submissions or {}).get("tickers") or []}
    if not listed:
        return None
    return ticker in listed


def classify(ticker, existing_submissions, incoming_submissions):
    """Classify a conflict from what each issuer's own SEC submissions say.

    The question is not which row is newer but whether SEC itself has moved the
    ticker. Only when both issuers' submissions are known and agree on the move is
    the existing mapping called stale; every doubt resolves to AMBIGUOUS, which
    changes nothing.
    """
    existing_lists = lists_ticker(existing_submissions, ticker)
    incoming_lists = lists_ticker(incoming_submissions, ticker)
    if existing_lists is False and incoming_lists is True:
        return STALE
    if existing_lists is True and incoming_lists is False:
        return INCOMING_WRONG
    return AMBIGUOUS


# --- evidence --------------------------------------------------------------------


def fetch_submissions(conn, cik, *, live=True):
    """Return ``(payload, source, retrieved)`` for a CIK, preferring SEC over storage."""
    if live:
        try:
            return get_submissions(cik), "sec_live", datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # noqa: BLE001 - fall back to what is stored
            print(f"  live submissions unavailable for CIK {cik}: {exc}", file=sys.stderr)
    row = (
        conn.execute(
            text("SELECT raw_payload, retrieved_at FROM raw.sec_submissions WHERE cik = :cik"),
            {"cik": cik},
        )
        .mappings()
        .first()
    )
    if row and isinstance(row["raw_payload"], dict):
        return row["raw_payload"], "stored", row["retrieved_at"].isoformat()
    return None, "unavailable", None


def current_conflicts(conn, entries, only_ticker=None):
    """The conflicts the stage would report, by the stage's own definition."""
    owners = prt._referenced_ticker_owners(conn)
    found, seen = [], set()
    for entry in entries:
        normalised = prt._normalise_entry(entry)
        if normalised is None:
            continue
        ticker, cik, title = normalised
        if only_ticker and ticker != only_ticker:
            continue
        conflict = prt._conflict_record(owners, ticker, cik, title)
        if conflict and (ticker, cik) not in seen:
            seen.add((ticker, cik))
            found.append(conflict)
    return found


def evidence_for(conn, conflict, *, live=True):
    """Gather and classify the evidence for one conflict."""
    ticker = conflict["ticker"]
    existing, existing_source, existing_when = fetch_submissions(
        conn, conflict["existing_cik"], live=live
    )
    incoming, incoming_source, incoming_when = fetch_submissions(
        conn, conflict["incoming_cik"], live=live
    )
    securities = (
        conn.execute(
            text("""
            SELECT security_id::text AS security_id, security_type, active, created_at::date AS created
            FROM reference.securities WHERE ticker = :t AND cik = :c ORDER BY created_at
        """),
            {"t": ticker, "c": conflict["existing_cik"]},
        )
        .mappings()
        .all()
    )
    siblings = (
        conn.execute(
            text("""
            SELECT ticker FROM raw.company_ticker WHERE cik = :c AND ticker <> :t ORDER BY ticker
        """),
            {"c": conflict["existing_cik"], "t": ticker},
        )
        .scalars()
        .all()
    )
    return {
        "conflict": conflict,
        "classification": classify(ticker, existing, incoming),
        "existing_issuer_lists_ticker": lists_ticker(existing, ticker),
        "incoming_issuer_lists_ticker": lists_ticker(incoming, ticker),
        "existing_submissions": {
            "source": existing_source,
            "retrieved": existing_when,
            "tickers": (existing or {}).get("tickers"),
        },
        "incoming_submissions": {
            "source": incoming_source,
            "retrieved": incoming_when,
            "tickers": (incoming or {}).get("tickers"),
        },
        "existing_securities": [dict(row, created=str(row["created"])) for row in securities],
        "existing_issuer_other_tickers": list(siblings),
    }


# --- what a release would remove -------------------------------------------------


def foreign_keys(conn):
    """Every foreign key between project tables, as dicts keyed by child and parent."""
    rows = (
        conn.execute(
            text("""
            SELECT con.conrelid::regclass::text AS child,
                   con.confrelid::regclass::text AS parent,
                   ARRAY(SELECT a.attname::text FROM unnest(con.conkey) WITH ORDINALITY k(n, o)
                           JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n
                          ORDER BY k.o) AS child_cols,
                   ARRAY(SELECT a.attname::text FROM unnest(con.confkey) WITH ORDINALITY k(n, o)
                           JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.n
                          ORDER BY k.o) AS parent_cols
            FROM pg_constraint con
            JOIN pg_namespace ns ON ns.oid = con.connamespace
            WHERE con.contype = 'f'
              AND ns.nspname IN ('audit','clean','fundamentals','model','preferred','raw','reference')
        """)
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def dependent_graph(fks):
    """Tables reachable from the root through foreign keys, and the edges between them.

    Returns ``(order, edges)``: ``order`` lists tables children-first so deleting in
    that order never violates a constraint, and ``edges[table]`` are the foreign keys
    that make a row of ``table`` doomed when its parent row is. Raises on a cycle,
    because a delete order cannot be derived for one.
    """
    # The root is also a *child* of raw.company_ticker; that edge points away from
    # the doomed set and is not a dependency to follow.
    by_parent = {}
    for fk in fks:
        by_parent.setdefault(fk["parent"], []).append(fk)

    reachable, stack = {ROOT_TABLE}, [ROOT_TABLE]
    while stack:
        parent = stack.pop()
        for fk in by_parent.get(parent, []):
            if fk["child"] not in reachable:
                reachable.add(fk["child"])
                stack.append(fk["child"])

    edges = {
        table: [
            fk
            for fk in fks
            if fk["child"] == table and fk["parent"] in reachable and fk["parent"] != table
        ]
        for table in reachable
        if table != ROOT_TABLE
    }

    order, state = [], {}

    def visit(table):
        if state.get(table) == "done":
            return
        if state.get(table) == "active":
            raise RuntimeError(
                f"foreign-key cycle through {table}; refusing to derive a delete order"
            )
        state[table] = "active"
        for fk in by_parent.get(table, []):
            if fk["child"] in reachable and fk["child"] != table:
                visit(fk["child"])
        state[table] = "done"
        order.append(table)

    visit(ROOT_TABLE)
    # ``order`` is post-order over children-before-parent, which is what a delete needs.
    return order, edges


def doomed_predicate(table, edges, alias="t", depth=0):
    """SQL that is true for the rows of ``table`` that belong to the doomed set.

    The doomed set is the stale securities (bound as ``:sids``) plus every row that
    references one of them, directly or through another doomed table. Built from
    EXISTS chains so composite keys need no special case.
    """
    if table == ROOT_TABLE:
        return f"{alias}.{ROOT_KEY}::text = ANY(:sids)"
    clauses = []
    for fk in edges[table]:
        parent_alias = f"p{depth}"
        join = " AND ".join(
            f"{parent_alias}.{pc} = {alias}.{cc}"
            for cc, pc in zip(fk["child_cols"], fk["parent_cols"])
        )
        inner = doomed_predicate(fk["parent"], edges, parent_alias, depth + 1)
        clauses.append(
            f"EXISTS (SELECT 1 FROM {fk['parent']} {parent_alias} WHERE {join} AND {inner})"
        )
    return "(" + " OR ".join(clauses) + ")"


def plan_release(conn, conflict):
    """Work out exactly what removing the stale mapping would delete, without deleting."""
    sids = (
        conn.execute(
            text(
                "SELECT security_id::text FROM reference.securities WHERE ticker = :t AND cik = :c"
            ),
            {"t": conflict["ticker"], "c": conflict["existing_cik"]},
        )
        .scalars()
        .all()
    )
    order, edges = dependent_graph(foreign_keys(conn))
    tables = []
    for table in order:
        predicate = doomed_predicate(table, edges)
        count = conn.execute(
            text(f"SELECT count(*) FROM {table} t WHERE {predicate}"), {"sids": sids}
        ).scalar()
        tables.append({"table": table, "predicate": predicate, "rows": int(count)})
    return {"security_ids": sids, "tables": tables}


def archive_rows(conn, plan, path, header):
    """Write every doomed row to ``path`` as JSON and flush it to disk. Raises on failure."""
    body = {"header": header, "rows": {}}
    for item in plan["tables"]:
        if not item["rows"]:
            continue
        rows = conn.execute(
            text(f"SELECT to_jsonb(t) FROM {item['table']} t WHERE {item['predicate']}"),
            {"sids": plan["security_ids"]},
        ).scalars()
        body["rows"][item["table"]] = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    return {table: len(rows) for table, rows in body["rows"].items()}


def perform_release(conn, conflict, plan, archive_path, header, registry_note):
    """Archive, delete, verify and record. Runs in the caller's transaction; never commits.

    The caller owns the transaction so a failure at any step, including the check at
    the end, rolls back everything but the archive file.
    """
    archived = archive_rows(conn, plan, archive_path, header)
    for item in plan["tables"]:
        if item["rows"] != archived.get(item["table"], 0):
            raise RuntimeError(f"archive does not match the plan for {item['table']}; aborting")

    deleted = {}
    for item in plan["tables"]:  # children first, root last
        result = conn.execute(
            text(f"DELETE FROM {item['table']} t WHERE {item['predicate']}"),
            {"sids": plan["security_ids"]},
        )
        deleted[item["table"]] = result.rowcount
        if result.rowcount != item["rows"]:
            raise RuntimeError(
                f"{item['table']}: deleted {result.rowcount} rows, planned {item['rows']}; aborting"
            )

    still = conn.execute(
        text("SELECT count(*) FROM reference.securities WHERE ticker = :t AND cik = :c"),
        {"t": conflict["ticker"], "c": conflict["existing_cik"]},
    ).scalar()
    if still:
        raise RuntimeError("the stale mapping is still referenced after the delete; aborting")

    for sid in plan["security_ids"]:
        conn.execute(
            text("""
            INSERT INTO audit.quarantined_values
                (table_schema, table_name, column_name, row_key, cik, ticker,
                 observed_value, reason, rule, resolved_at, resolution_note)
            VALUES ('reference', 'securities', 'ticker', :sid, :cik, :ticker,
                    :observed, :reason, 'TICKER_CIK_CONFLICT', now(), :note)
            ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value)
            DO NOTHING
        """),
            {
                "sid": sid,
                "cik": conflict["existing_cik"],
                "ticker": conflict["ticker"][:REGISTRY_TICKER_WIDTH],
                "observed": conflict["ticker"],
                "reason": (
                    f"ticker reassigned from {conflict['existing_issuer']} "
                    f"(CIK {conflict['existing_cik']}) to {conflict['incoming_issuer']} "
                    f"(CIK {conflict['incoming_cik']})"
                ),
                "note": registry_note,
            },
        )
    return deleted


# --- command line ----------------------------------------------------------------


def _load_snapshot_entries():
    return list(get_company_tickers().values())


def cmd_review(args):
    entries = _load_snapshot_entries()
    with engine.connect() as conn:
        conflicts = current_conflicts(conn, entries, args.ticker)
        reports = [evidence_for(conn, c, live=not args.stored_only) for c in conflicts]
    if args.json:
        print(json.dumps(reports, indent=2, default=str))
        return 0
    if not reports:
        print("No open ticker/CIK conflicts.")
        return 0
    for report in reports:
        c = report["conflict"]
        print(f"{c['ticker']}: {report['classification']}")
        print(f"  existing: {c['existing_issuer']} (CIK {c['existing_cik']})")
        print(
            f"            lists ticker: {report['existing_issuer_lists_ticker']}  "
            f"[{report['existing_submissions']['source']}]  "
            f"other tickers: {report['existing_issuer_other_tickers'] or 'none'}"
        )
        print(f"  incoming: {c['incoming_issuer']} (CIK {c['incoming_cik']})")
        print(
            f"            lists ticker: {report['incoming_issuer_lists_ticker']}  "
            f"[{report['incoming_submissions']['source']}]"
        )
        print(f"  existing securities: {len(report['existing_securities'])}")
        print(f"  next: {_next_step(report['classification'])}")
    return 0


def _next_step(classification):
    return {
        STALE: "release --ticker <T> --reviewed-by <you>  (dry-run first)",
        INCOMING_WRONG: "leave it; the incoming SEC record does not list the ticker",
        AMBIGUOUS: 'leave it, or verify externally and release with --basis "<evidence>"',
    }[classification]


def cmd_release(args):
    ticker = args.ticker.strip().upper()
    if args.execute and args.confirm != ticker:
        print(f"--execute requires --confirm {ticker}", file=sys.stderr)
        return 2

    entries = _load_snapshot_entries()
    lock = None
    try:
        if args.execute:
            try:
                lock = _acquire_run_lock()
            except PipelineAlreadyRunning as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2

        with engine.connect() as conn:
            conflicts = current_conflicts(conn, entries, ticker)
            if not conflicts:
                print(f"{ticker} has no open conflict; nothing to release.", file=sys.stderr)
                return 1
            conflict = conflicts[0]
            report = evidence_for(conn, conflict, live=not args.stored_only)
            verdict = report["classification"]

            if verdict == INCOMING_WRONG:
                print(
                    "refused: SEC still lists the ticker under the existing CIK and not "
                    "the incoming one. Releasing it would remove the correct mapping.",
                    file=sys.stderr,
                )
                return 1
            if verdict == AMBIGUOUS and not args.basis:
                print(
                    "refused: the evidence is ambiguous. Release only with --basis "
                    "naming the evidence that settles it.",
                    file=sys.stderr,
                )
                return 1

            plan = plan_release(conn, conflict)
            if not plan["security_ids"]:
                print(
                    "refused: no securities row references the existing mapping.", file=sys.stderr
                )
                return 1

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive_path = ARCHIVE_DIR / f"{ticker}_{conflict['existing_cik']}_{stamp}.json"
            header = {
                "ticker": ticker,
                "released_at": stamp,
                "reviewed_by": args.reviewed_by,
                "classification": verdict,
                "basis": args.basis,
                "conflict": conflict,
                "evidence": {
                    k: report[k]
                    for k in (
                        "existing_issuer_lists_ticker",
                        "incoming_issuer_lists_ticker",
                        "existing_submissions",
                        "incoming_submissions",
                        "existing_issuer_other_tickers",
                    )
                },
                "security_ids": plan["security_ids"],
            }

            print(
                json.dumps(
                    {
                        "mode": "EXECUTE" if args.execute else "DRY RUN",
                        "classification": verdict,
                        "basis": args.basis,
                        "plan": [
                            {k: t[k] for k in ("table", "rows")}
                            for t in plan["tables"]
                            if t["rows"]
                        ],
                    },
                    indent=2,
                )
            )
            if not args.execute:
                print(
                    "\nDry run only. Re-run with --execute --confirm "
                    f"{ticker} to apply; the archive goes to {archive_path}."
                )
                return 0

            note = (
                f"released by {args.reviewed_by}; classification {verdict}; "
                f"basis: {args.basis or 'SEC submissions'}; archive {archive_path.name}"
            )
            # End the read transaction the review opened, then re-plan inside the write
            # transaction so the plan, the archive and the delete see the same rows.
            conn.rollback()
            with conn.begin():
                plan = plan_release(conn, conflict)
                deleted = perform_release(conn, conflict, plan, archive_path, header, note)
            print(
                f"\nReleased {ticker}: deleted {sum(deleted.values())} rows; archive {archive_path}."
            )
            print("The next ordinary run of populate_raw_tables will ingest the incoming CIK.")
            return 0
    finally:
        _release_run_lock(lock)


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="read-only evidence and classification")
    review.add_argument("--ticker", type=lambda v: v.strip().upper(), default=None)
    review.add_argument(
        "--stored-only",
        action="store_true",
        help="use stored submissions instead of fetching them from SEC",
    )
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)

    release = sub.add_parser("release", help="retire a stale mapping (dry-run unless --execute)")
    release.add_argument("--ticker", required=True)
    release.add_argument("--reviewed-by", required=True)
    release.add_argument(
        "--basis",
        default=None,
        help="required when the review is AMBIGUOUS: the evidence that settles it",
    )
    release.add_argument("--stored-only", action="store_true")
    release.add_argument("--execute", action="store_true")
    release.add_argument("--confirm", default=None, help="repeat the ticker to confirm --execute")
    release.set_defaults(func=cmd_release)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
