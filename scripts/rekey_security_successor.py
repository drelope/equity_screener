"""Move a security to its successor issuer's CIK, keeping its identity and history.

When a company reorganises under a new holding company (a Delaware 251(g) merger, filed on
an 8-K12B), the same shares trade under the same ticker but SEC now files them under a new
CIK. ``scripts.resolve_ticker_conflict release`` handles that by deleting the old security
and everything attached to it: years of prices, dividends, point-in-time fundamentals and
model rows, none of which a new registrant can regenerate. This tool is for the case where
the equity really is the same instrument: it re-points the existing ``security_id`` at the
new CIK instead, so all of that history stays attached.

Do not use it for a ticker that has been reassigned to an unrelated company; that is what
``release`` is for. The ``--basis`` must name the filing that establishes succession.

What changes, in one transaction:

* ``raw.company_ticker``: the ticker's row takes the CIK, title and payload SEC now lists.
* ``reference.securities``: ``cik`` and ``issuer_id`` move to the successor.
* ``clean.ticker_profile``: ``cik`` follows.
* ``reference.security_identifiers``: the old CIK is closed the day before ``--effective-date``
  and the new one opens on it.
* ``audit.quarantined_values``: the resolution is recorded.

``security_id`` is unchanged, so every table keyed on it is untouched; their row counts are
checked before and after. ``raw.company_ticker`` and ``reference.securities`` reference each
other through a composite foreign key that is not deferrable, so the constraint is made
deferrable inside the transaction and restored before commit. Postgres DDL is transactional:
any failed check rolls the whole thing back.

``--dry-run`` (the default) performs the entire change, runs every check, then rolls back, so
it proves the change works against the real database without committing anything.

Usage:
    python -m scripts.rekey_security_successor --ticker NAVI --new-cik 0002152623 \\
        --effective-date 2026-10-28 --reviewed-by NAME --basis "8-K12B 0001193125-26-436899 ..."
    ... --execute --confirm NAVI
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts.resolve_ticker_conflict import current_conflicts
from scripts.run_full_etl import PipelineAlreadyRunning, _acquire_run_lock, _release_run_lock
from src.crispdm.db import engine
from src.crispdm.sec_client import get_company_tickers

ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "data" / "ticker_conflict_archive"
FK_NAME = "fk_securities_company_ticker"
RULE = "TICKER_CIK_CONFLICT"
REGISTRY_TICKER_WIDTH = 16  # audit.quarantined_values.ticker is VARCHAR(16)

#: Tables keyed on security_id whose row counts must be identical before and after: the
#: whole point of a re-key is that none of this history moves or disappears.
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
    "raw.ticker_profile",
)


class RekeyRefused(Exception):
    """A pre-condition or post-condition failed; nothing was changed."""


def normalize_cik(value) -> str:
    return str(int(str(value).strip())).zfill(10)


def sec_entry(entries, ticker: str, cik: str):
    """The SEC ticker-file entry assigning ``ticker`` to ``cik``, or None."""
    for entry in entries:
        if (
            str(entry.get("ticker", "")).upper() == ticker
            and normalize_cik(entry.get("cik_str")) == cik
        ):
            return entry
    return None


def identifier_dates(effective: date) -> tuple[date, date]:
    """``(old_valid_to, new_valid_from)``: contiguous, no day without or with both CIKs."""
    return effective - timedelta(days=1), effective


def history_counts(conn, security_id) -> dict[str, int]:
    out = {}
    for table in HISTORY_TABLES:
        out[table] = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE security_id = :s"),  # noqa: S608
            {"s": security_id},
        ).scalar()
    return out


def preconditions(conn, ticker, new_cik, entries):
    """Facts the re-key depends on. Raises RekeyRefused unless every one holds."""
    entry = sec_entry(entries, ticker, new_cik)
    if entry is None:
        raise RekeyRefused(
            f"SEC's ticker file does not list {ticker} under CIK {new_cik}; refusing to move "
            "the security to a CIK SEC does not assign the ticker to"
        )
    mapped = conn.execute(
        text("SELECT cik FROM raw.company_ticker WHERE ticker = :t"), {"t": ticker}
    ).scalar()
    if mapped is None:
        raise RekeyRefused(f"raw.company_ticker has no row for {ticker}")
    if mapped == new_cik:
        raise RekeyRefused(f"{ticker} is already mapped to CIK {new_cik}; nothing to do")
    securities = (
        conn.execute(
            text(
                "SELECT security_id, issuer_id, security_type, active FROM reference.securities "
                "WHERE ticker = :t AND cik = :c"
            ),
            {"t": ticker, "c": mapped},
        )
        .mappings()
        .all()
    )
    if len(securities) != 1:
        raise RekeyRefused(
            f"expected exactly one reference.securities row for {ticker}/{mapped}, "
            f"found {len(securities)}"
        )
    taken = conn.execute(
        text("SELECT count(*) FROM reference.securities WHERE ticker = :t AND cik = :c"),
        {"t": ticker, "c": new_cik},
    ).scalar()
    if taken:
        raise RekeyRefused(f"{ticker} already has a reference.securities row under {new_cik}")
    issuer_id = conn.execute(
        text("SELECT issuer_id FROM reference.issuers WHERE cik = :c"), {"c": new_cik}
    ).scalar()
    if issuer_id is None:
        raise RekeyRefused(
            f"no reference.issuers row for {new_cik}; run populate_reference_tables --issuers"
        )
    return {
        "entry": entry,
        "old_cik": mapped,
        "security": dict(securities[0]),
        "issuer_id": issuer_id,
    }


def before_images(conn, ticker, old_cik, security_id):
    """The rows about to change, as JSON, for the archive."""
    queries = {
        "raw.company_ticker": (
            "SELECT to_jsonb(t) FROM raw.company_ticker t WHERE ticker = :t",
            {"t": ticker},
        ),
        "reference.securities": (
            "SELECT to_jsonb(t) FROM reference.securities t WHERE security_id = :s",
            {"s": security_id},
        ),
        "clean.ticker_profile": (
            "SELECT to_jsonb(t) FROM clean.ticker_profile t WHERE security_id = :s",
            {"s": security_id},
        ),
        "reference.security_identifiers": (
            "SELECT to_jsonb(t) FROM reference.security_identifiers t WHERE security_id = :s "
            "AND id_type = 'cik'",
            {"s": security_id},
        ),
    }
    return {
        table: list(conn.execute(text(sql), params).scalars())
        for table, (sql, params) in queries.items()
    }


def close_stage_conflict(conn, ticker, new_cik, note):
    """Resolve the conflict row populate_raw_tables registered for this ticker, if open.

    Stage 0 records ``(row_key=ticker, observed_value=incoming CIK)`` when it skips a
    conflicting ticker and sweeps the row closed on a later run once the SEC file no longer
    conflicts. Closing it here, with the reason, means the verification does not report a
    conflict that has been resolved until that stage next runs. Returns the rows closed.
    """
    return conn.execute(
        text(
            "UPDATE audit.quarantined_values SET resolved_at = now(), resolution_note = :note "
            "WHERE rule = :rule AND table_schema = 'raw' AND row_key = :ticker "
            "AND observed_value = :new AND resolved_at IS NULL"
        ),
        {"note": note, "rule": RULE, "ticker": ticker, "new": new_cik},
    ).rowcount


def apply_rekey(conn, ticker, new_cik, effective, basis, reviewed_by, entries, archive_path=None):
    """Perform and verify the re-key inside the caller's transaction. Never commits.

    Raises on any failed check; the caller's rollback then undoes everything. When
    ``archive_path`` is given the before-images are written (and fsynced) first.
    """
    facts = preconditions(conn, ticker, new_cik, entries)
    old_cik, security_id = facts["old_cik"], facts["security"]["security_id"]
    entry = facts["entry"]
    before = history_counts(conn, security_id)
    images = before_images(conn, ticker, old_cik, security_id)
    if archive_path is not None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with open(archive_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "ticker": ticker,
                    "old_cik": old_cik,
                    "new_cik": new_cik,
                    "effective_date": effective,
                    "reviewed_by": reviewed_by,
                    "basis": basis,
                    "security_id": security_id,
                    "history_counts": before,
                    "rows": images,
                },
                handle,
                indent=2,
                default=str,
            )
            handle.flush()
            os.fsync(handle.fileno())

    # The two tables reference each other through a non-deferrable composite FK, so neither
    # can move first. Make it deferrable for this transaction only.
    conn.execute(
        text(
            f"ALTER TABLE reference.securities ALTER CONSTRAINT {FK_NAME} DEFERRABLE INITIALLY IMMEDIATE"
        )
    )
    conn.execute(text(f"SET CONSTRAINTS reference.{FK_NAME} DEFERRED"))

    moved = conn.execute(
        text(
            "UPDATE raw.company_ticker SET cik = :new, title = :title, source_url = :url, "
            "raw_payload = CAST(:payload AS jsonb), retrieved_at = now() "
            "WHERE ticker = :t AND cik = :old"
        ),
        {
            "new": new_cik,
            "title": entry.get("title") or "",
            "url": "https://www.sec.gov/files/company_tickers.json",
            "payload": json.dumps(entry),
            "t": ticker,
            "old": old_cik,
        },
    ).rowcount
    if moved != 1:
        raise RekeyRefused(f"raw.company_ticker update touched {moved} rows, expected 1")
    updated = conn.execute(
        text(
            "UPDATE reference.securities SET cik = :new, issuer_id = :issuer, updated_at = now() "
            "WHERE security_id = :s AND cik = :old"
        ),
        {"new": new_cik, "issuer": facts["issuer_id"], "s": security_id, "old": old_cik},
    ).rowcount
    if updated != 1:
        raise RekeyRefused(f"reference.securities update touched {updated} rows, expected 1")
    conn.execute(
        text("UPDATE clean.ticker_profile SET cik = :new WHERE security_id = :s"),
        {"new": new_cik, "s": security_id},
    )

    old_to, new_from = identifier_dates(effective)
    conn.execute(
        text(
            "UPDATE reference.security_identifiers SET valid_to = :valid_to "
            "WHERE security_id = :s AND id_type = 'cik' AND id_value = :old AND valid_to IS NULL"
        ),
        {"valid_to": old_to, "s": security_id, "old": old_cik},
    )
    conn.execute(
        text(
            "INSERT INTO reference.security_identifiers "
            "(security_id, id_type, id_value, valid_from, source) "
            "VALUES (:s, 'cik', :new, :valid_from, :source) ON CONFLICT DO NOTHING"
        ),
        {
            "s": security_id,
            "new": new_cik,
            "valid_from": new_from,
            "source": f"successor_issuer: {basis}"[:64],
        },
    )

    # Verify the foreign key now (this is what the non-deferrable constraint would have
    # refused mid-way), then put the constraint back exactly as it was.
    conn.execute(text(f"SET CONSTRAINTS reference.{FK_NAME} IMMEDIATE"))
    conn.execute(
        text(f"ALTER TABLE reference.securities ALTER CONSTRAINT {FK_NAME} NOT DEFERRABLE")
    )

    after = history_counts(conn, security_id)
    if after != before:
        raise RekeyRefused(f"history row counts changed: before {before}, after {after}")
    stale = conn.execute(
        text(
            "SELECT count(*) FROM reference.securities s JOIN raw.company_ticker c "
            "ON c.ticker = s.ticker AND c.cik = s.cik WHERE s.security_id = :s"
        ),
        {"s": security_id},
    ).scalar()
    if stale != 1:
        raise RekeyRefused("the security no longer matches its raw.company_ticker row")
    still = current_conflicts(conn, entries, ticker)
    if still:
        raise RekeyRefused(f"{ticker} still has an open ticker/CIK conflict after the re-key")
    deferrable = conn.execute(
        text("SELECT condeferrable FROM pg_constraint WHERE conname = :n"), {"n": FK_NAME}
    ).scalar()
    if deferrable:
        raise RekeyRefused("the foreign key was left deferrable")

    conn.execute(
        text("""
        INSERT INTO audit.quarantined_values
            (table_schema, table_name, column_name, row_key, cik, ticker,
             observed_value, reason, rule, resolved_at, resolution_note)
        VALUES ('reference', 'securities', 'cik', :sid, :cik, :ticker, :observed,
                :reason, :rule, now(), :note)
        ON CONFLICT (table_schema, table_name, column_name, row_key, observed_value) DO NOTHING
    """),
        {
            "sid": str(security_id),
            "cik": old_cik,
            "ticker": ticker[:REGISTRY_TICKER_WIDTH],
            "observed": f"{ticker}:{old_cik}",
            "reason": f"{ticker} moved to successor issuer CIK {new_cik} (was CIK {old_cik})",
            "rule": RULE,
            "note": f"re-keyed by {reviewed_by}; effective {effective}; basis: {basis}",
        },
    )
    closed = close_stage_conflict(
        conn,
        ticker,
        new_cik,
        f"resolved by successor re-key (reviewed by {reviewed_by}); basis: {basis}",
    )
    return {
        "stage_conflict_rows_closed": closed,
        "ticker": ticker,
        "security_id": str(security_id),
        "old_cik": old_cik,
        "new_cik": new_cik,
        "effective_date": str(effective),
        "history_rows_preserved": sum(after.values()),
        "history_counts": after,
        "old_identifier_valid_to": str(old_to),
        "new_identifier_valid_from": str(new_from),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--new-cik", required=True)
    parser.add_argument("--effective-date", required=True, type=date.fromisoformat)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--basis", required=True, help="The filing that establishes succession.")
    parser.add_argument("--execute", action="store_true", help="Commit. Without it, roll back.")
    parser.add_argument("--confirm", help="Must equal the ticker when --execute is given.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    ticker, new_cik = args.ticker.strip().upper(), normalize_cik(args.new_cik)
    if args.execute and args.confirm != ticker:
        print(f"--execute requires --confirm {ticker}", file=sys.stderr)
        return 2
    try:
        lock = _acquire_run_lock()
    except PipelineAlreadyRunning as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    try:
        entries = list(get_company_tickers().values())
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = ARCHIVE_DIR / f"rekey_{ticker}_{new_cik}_{stamp}.json" if args.execute else None
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                summary = apply_rekey(
                    conn,
                    ticker,
                    new_cik,
                    args.effective_date,
                    args.basis,
                    args.reviewed_by,
                    entries,
                    archive_path=archive,
                )
            except RekeyRefused as exc:
                transaction.rollback()
                print(f"refused, nothing changed: {exc}", file=sys.stderr)
                return 1
            except Exception:
                transaction.rollback()
                raise
            if args.execute:
                transaction.commit()
            else:
                transaction.rollback()
        mode = (
            "EXECUTED"
            if args.execute
            else "DRY RUN (every change was made, verified, then rolled back)"
        )
        print(json.dumps({"mode": mode, **summary}, indent=2))
        if args.execute:
            print(f"\nArchive of the before-images: {archive}")
            print("The next populate_raw_tables run will find no conflict for the ticker.")
        else:
            print(f"\nRe-run with --execute --confirm {ticker} to commit.")
        return 0
    finally:
        _release_run_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
