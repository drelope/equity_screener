"""Bulk-first EDGAR ingestion from SEC's ``submissions.zip`` and ``companyfacts.zip``.

A full rebuild through the per-CIK API is one request per issuer per payload,
throttled to SEC's fair-access rate. The two bulk files carry every filer in one
download each, so a rebuild needs no per-CIK ``companyfacts`` requests. Per-CIK
calls remain for targeted backfills (``scripts.populate_companyfacts``).

Only CIKs the warehouse tracks (``reference.securities``) are loaded; the bulk
files hold roughly 800k filers. A payload is written only when its content hash
differs from the stored one, so an unchanged issuer costs a hash comparison and no
write. Rows are written by the same upsert functions as the per-CIK path, so a
bulk-loaded row is indistinguishable from a fetched one.

    python -m scripts.load_sec_bulk --download            # fetch both zips, then load
    python -m scripts.load_sec_bulk --facts path/companyfacts.zip --submissions path/submissions.zip
    python -m scripts.load_sec_bulk --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import text

from scripts.populate_companyfacts import (
    normalize_cik,
    payload_hash,
    upsert_classification,
    upsert_companyfacts,
    upsert_submissions,
)
from src.crispdm.db import engine, read_df
from src.crispdm.sec_client import HEADERS, SEC_SESSION, build_companyfacts_concept_groups

BULK_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "sec_bulk"
FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
#: ``submissions.zip`` also holds ``CIK##########-submissions-001.json`` overflow
#: pages; only the primary per-CIK file is the payload the warehouse stores.
MEMBER = re.compile(r"^CIK(\d{10})\.json$")


def download(url: str, dest: Path) -> bool:
    """Stream ``url`` to ``dest``; return False when SEC says the local copy is current."""
    headers = dict(HEADERS)
    if dest.exists():
        headers["If-Modified-Since"] = _http_date(dest.stat().st_mtime)
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = SEC_SESSION.get(url, headers=headers, stream=True, timeout=(10, 300))
    if response.status_code == 304:
        return False
    response.raise_for_status()
    partial = dest.with_suffix(dest.suffix + ".part")
    with partial.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1 << 20):
            handle.write(chunk)
    partial.replace(dest)
    return True


def _http_date(timestamp: float) -> str:
    from email.utils import formatdate

    return formatdate(timestamp, usegmt=True)


def changed_payloads(
    archive: zipfile.ZipFile,
    stored_hashes: dict[str, str],
    targets: set[str],
    unchanged: list[str] | None = None,
) -> Iterator[tuple[str, dict, str]]:
    """Yield ``(cik, payload, hash)`` for tracked CIKs whose payload is new or changed.

    CIKs present in the archive with an identical stored hash are appended to
    ``unchanged`` when given, so the caller can record that they were verified.
    """
    for name in archive.namelist():
        match = MEMBER.match(name)
        if not match or match.group(1) not in targets:
            continue
        cik = match.group(1)
        payload = json.loads(archive.read(name))
        digest = payload_hash(payload)
        if stored_hashes.get(cik) != digest:
            yield cik, payload, digest
        elif unchanged is not None:
            unchanged.append(cik)


def tracked_ciks() -> tuple[set[str], dict[str, str]]:
    frame = read_df(
        "SELECT DISTINCT ON (cik) cik, ticker FROM reference.securities "
        "WHERE cik IS NOT NULL AND active = TRUE ORDER BY cik, ticker"
    )
    tickers = {normalize_cik(r.cik): str(r.ticker) for r in frame.itertuples()}
    return set(tickers), tickers


def stored_hashes(table: str) -> dict[str, str]:
    frame = read_df(f"SELECT cik, content_hash FROM {table}")  # noqa: S608 - fixed table names
    return {normalize_cik(r.cik): r.content_hash for r in frame.itertuples()}


def mark_verified(table: str, ciks: list[str]) -> int:
    """Stamp ``retrieved_at`` on rows the bulk file confirmed unchanged.

    ``retrieved_at`` means "last confirmed current against SEC", the reading the
    freshness check relies on: it ages these tables by their *oldest* row. Without
    this, an unchanged issuer keeps the timestamp of its last change and a bulk run
    that verified every row would still read as stale. Only a timestamp column is
    updated, so the stored payload is not rewritten.
    """
    if not ciks:
        return 0
    with engine.begin() as conn:
        for start in range(0, len(ciks), 5000):
            conn.execute(
                text(f"UPDATE {table} SET retrieved_at = now() WHERE cik = ANY(:ciks)"),  # noqa: S608
                {"ciks": ciks[start : start + 5000]},
            )
    return len(ciks)


def load_submissions(path: Path, targets: set[str], dry_run: bool) -> tuple[int, int]:
    stored = stored_hashes("raw.sec_submissions")
    changed = 0
    unchanged: list[str] = []
    with zipfile.ZipFile(path) as archive, engine.begin() as conn:
        for cik, payload, _digest in changed_payloads(archive, stored, targets, unchanged):
            changed += 1
            if not dry_run:
                upsert_submissions(conn, cik, payload.get("name"), payload)
    if not dry_run:
        mark_verified("raw.sec_submissions", unchanged)
    return changed, len(targets) - changed


def load_facts(path: Path, targets: set[str], tickers: dict[str, str], dry_run: bool):
    stored = stored_hashes("raw.companyfacts")
    changed = 0
    unchanged: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for cik, payload, _digest in changed_payloads(archive, stored, targets, unchanged):
            changed += 1
            if dry_run:
                continue
            facts = {
                "cik": cik,
                "company": payload.get("entityName"),
                **build_companyfacts_concept_groups(payload),
                "full_facts": payload,
            }
            # One transaction per issuer: a multi-MB payload must not hold a
            # connection and a lock for the whole file.
            with engine.begin() as conn:
                upsert_companyfacts(conn, cik, facts)
                upsert_classification(conn, cik, tickers.get(cik), facts)
            if changed % 250 == 0:
                print(f"  facts: {changed} written", flush=True)
    if not dry_run:
        mark_verified("raw.companyfacts", unchanged)
    return changed, len(targets) - changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, default=BULK_DIR / "companyfacts.zip")
    parser.add_argument("--submissions", type=Path, default=BULK_DIR / "submissions.zip")
    parser.add_argument("--download", action="store_true", help="Fetch both zips first.")
    parser.add_argument("--dry-run", action="store_true", help="Count changes; write nothing.")
    args = parser.parse_args()

    if args.download:
        for url, dest in ((SUBMISSIONS_URL, args.submissions), (FACTS_URL, args.facts)):
            print(f"{dest.name}: {'downloaded' if download(url, dest) else 'already current'}")
    missing = [p for p in (args.submissions, args.facts) if not p.exists()]
    if missing:
        print(f"missing {', '.join(map(str, missing))}; pass --download")
        return 1

    targets, tickers = tracked_ciks()
    print(f"{len(targets)} tracked CIKs")
    changed, unchanged = load_submissions(args.submissions, targets, args.dry_run)
    print(f"submissions: {changed} changed, {unchanged} unchanged or absent from the file")
    changed, unchanged = load_facts(args.facts, targets, tickers, args.dry_run)
    print(f"companyfacts: {changed} changed, {unchanged} unchanged or absent from the file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
