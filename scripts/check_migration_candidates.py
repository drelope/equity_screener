"""Validate numbered migration candidates without applying them.

Checks under ``docs/speckit-recovery/08-implementation-validation/sql-candidates/``:

- filenames match the migrator's ``V<version>_<slug>.sql`` pattern;
- candidate versions are unique, collision-free with ``sql/migrations/``, and
  strictly above the current on-disk maximum (V0045 gap is never reused);
- every candidate is declared in ``candidate-manifest.json`` and its SHA-256
  matches the file on disk;
- each candidate carries CANDIDATE/APPROVAL-GATES/ROLLBACK markers;
- forward candidate SQL contains no destructive statements (DROP/TRUNCATE/
  DELETE/UPDATE) outside comments — candidates are additive-only;
- manifest dependency references resolve and rollback files exist.

Exit 0 = candidates are internally consistent (not approved, not applied).
Exit 1 = consistency problem found. Exit 2 = usage/IO error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES_DIR = (
    PROJECT_ROOT / "docs" / "speckit-recovery" / "08-implementation-validation" / "sql-candidates"
)
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "migrations"
MANIFEST_NAME = "candidate-manifest.json"

FILENAME_RE = re.compile(r"^V(\d+)_([a-z0-9_]+)\.sql$", re.IGNORECASE)
DESTRUCTIVE_RE = re.compile(r"\b(DROP|TRUNCATE|DELETE|UPDATE)\b", re.IGNORECASE)
ALTER_DROP_RE = re.compile(r"\bALTER\s+TABLE\b[^;]*\bDROP\b", re.IGNORECASE | re.DOTALL)
TRIGGER_EVENT_RE = re.compile(
    r"\bBEFORE\s+(?:(?:INSERT|UPDATE|DELETE)(?:\s+OR\s+)?)+\s+ON\b",
    re.IGNORECASE,
)

REQUIRED_MANIFEST_FIELDS = (
    "version",
    "filename",
    "sha256",
    "area",
    "title",
    "requirements",
    "approval_gates",
    "depends_on_candidates",
    "soft_depends_on",
    "backfill_required",
    "rollback_file",
    "rehearsal_ref",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_sql_comments(sql_text: str) -> str:
    """Remove ``--`` line comments and ``/* ... */`` blocks without touching strings.

    Candidate checks only need a conservative scan for destructive keywords, so
    this deliberately keeps string literals intact and does not try to be a full
    SQL lexer. Dollar-quoted bodies are rare in these additive candidates.
    """
    out: list[str] = []
    i = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_single:
            out.append(ch)
            if ch == "'" and nxt == "'":
                out.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def discover_existing(migrations_dir: Path) -> dict[int, str]:
    existing: dict[int, str] = {}
    if not migrations_dir.exists():
        return existing
    for path in sorted(migrations_dir.glob("V*.sql")):
        match = FILENAME_RE.match(path.name)
        if match:
            existing[int(match.group(1))] = path.name
    return existing


def discover_candidate_files(candidates_dir: Path) -> dict[int, Path]:
    files: dict[int, Path] = {}
    for path in sorted(candidates_dir.glob("V*.sql")):
        match = FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(
                f"candidate filename does not match V<version>_<slug>.sql: {path.name}"
            )
        version = int(match.group(1))
        if version in files:
            raise ValueError(
                f"duplicate candidate version V{version}: {files[version].name}, {path.name}"
            )
        files[version] = path
    return files


def check_header(path: Path) -> list[str]:
    errs: list[str] = []
    header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:25])
    if "CANDIDATE: NOT APPLIED" not in header:
        errs.append(f"{path.name}: missing 'CANDIDATE: NOT APPLIED' header marker")
    if "APPROVAL-GATES:" not in header:
        errs.append(f"{path.name}: missing 'APPROVAL-GATES:' header marker")
    if "ROLLBACK:" not in header:
        errs.append(f"{path.name}: missing 'ROLLBACK:' header marker")
    return errs


def check_forward_sql(path: Path) -> list[str]:
    errs: list[str] = []
    body = strip_sql_comments(path.read_text(encoding="utf-8"))
    # ``CREATE TRIGGER ... BEFORE UPDATE OR DELETE ON ...`` is additive DDL, not a
    # destructive statement. Remove only the trigger event clause before scanning.
    body_for_scan = TRIGGER_EVENT_RE.sub("BEFORE ON", body)
    match = DESTRUCTIVE_RE.search(body_for_scan)
    if match:
        errs.append(
            f"{path.name}: destructive keyword {match.group(1).upper()!r} outside comments "
            "(candidates must be additive-only; put removals in rollback/)"
        )
    elif ALTER_DROP_RE.search(body):
        errs.append(f"{path.name}: ALTER TABLE ... DROP outside comments (additive-only violation)")
    return errs


def check_manifest(
    candidates_dir: Path, candidate_files: dict[int, Path], existing: dict[int, str]
) -> list[str]:
    errs: list[str] = []
    manifest_path = candidates_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return [f"missing manifest: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable manifest: {exc}"]

    if manifest.get("status") != "candidate_not_applied":
        errs.append("manifest.status must be 'candidate_not_applied'")
    max_existing = max(existing, default=0)
    baseline = manifest.get("baseline")
    if isinstance(baseline, dict) and "max_existing_version" in baseline:
        if baseline["max_existing_version"] != max_existing:
            errs.append(
                f"manifest baseline max_existing_version={baseline['max_existing_version']} "
                f"but sql/migrations max is V{max_existing}"
            )
    entries = manifest.get("candidates")
    if not isinstance(entries, list) or not entries:
        return errs + ["manifest.candidates must be a non-empty list"]

    by_version: dict[int, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errs.append("manifest candidate entry is not an object")
            continue
        missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in entry]
        if missing:
            errs.append(
                f"manifest entry {entry.get('filename', '?')}: missing {', '.join(missing)}"
            )
            continue
        version = entry["version"]
        if not isinstance(version, int):
            errs.append(f"manifest entry {entry.get('filename', '?')}: version must be an integer")
            continue
        if version in by_version:
            errs.append(f"manifest declares duplicate version V{version}")
        by_version[version] = entry
        if not isinstance(entry["requirements"], list) or not entry["requirements"]:
            errs.append(f"{entry['filename']}: requirements must be a non-empty list")
        if not isinstance(entry["approval_gates"], list) or not entry["approval_gates"]:
            errs.append(f"{entry['filename']}: approval_gates must be a non-empty list")

    for version, path in candidate_files.items():
        if version not in by_version:
            errs.append(f"{path.name}: not declared in {MANIFEST_NAME}")
            continue
        entry = by_version[version]
        if entry.get("filename") != path.name:
            errs.append(f"V{version}: manifest filename {entry.get('filename')!r} != {path.name!r}")
        if entry.get("sha256") != sha256_file(path):
            errs.append(f"{path.name}: manifest sha256 does not match file on disk")
        rollback = candidates_dir / str(entry.get("rollback_file", ""))
        if not rollback.exists():
            errs.append(f"{path.name}: rollback file missing: {entry.get('rollback_file')}")
        elif "ROLLBACK CANDIDATE: NOT APPLIED" not in "\n".join(
            rollback.read_text(encoding="utf-8").splitlines()[:10]
        ):
            errs.append(
                f"{entry.get('rollback_file')}: missing 'ROLLBACK CANDIDATE: NOT APPLIED' marker"
            )

    for version, entry in by_version.items():
        if version not in candidate_files:
            errs.append(f"manifest declares V{version} but no candidate file exists")
        if version in existing:
            errs.append(f"V{version}: version collides with existing migration {existing[version]}")
        if version <= max_existing:
            errs.append(
                f"V{version}: candidate version must be greater than current max V{max_existing} "
                "(do not reuse the V0045 gap)"
            )
        for dep in entry.get("depends_on_candidates", []) + entry.get("soft_depends_on", []):
            if dep not in by_version:
                errs.append(f"V{version}: dependency V{dep} is not declared in the manifest")

    undeclared = sorted(set(candidate_files) - set(by_version))
    if undeclared:
        errs.append(
            f"manifest is missing candidate files: {', '.join(f'V{v}' for v in undeclared)}"
        )
    return errs


def run(candidates_dir: Path, migrations_dir: Path) -> tuple[list[str], dict]:
    summary: dict = {
        "candidates_dir": str(candidates_dir),
        "migrations_dir": str(migrations_dir),
        "status": "pass",
        "candidates": [],
        "issues": [],
    }
    if candidates_dir.resolve() == migrations_dir.resolve():
        return [
            "candidates directory must not be sql/migrations (migrator would discover them)"
        ], summary
    try:
        existing = discover_existing(migrations_dir)
        candidate_files = discover_candidate_files(candidates_dir)
    except ValueError as exc:
        return [str(exc)], summary

    errs: list[str] = []
    if not candidate_files:
        errs.append(f"no V*.sql candidates found in {candidates_dir}")
    max_existing = max(existing, default=0)
    summary["existing_max_version"] = max_existing
    summary["candidate_versions"] = sorted(candidate_files)

    for version, path in sorted(candidate_files.items()):
        errs.extend(check_header(path))
        errs.extend(check_forward_sql(path))
        summary["candidates"].append(
            {"version": version, "filename": path.name, "sha256": sha256_file(path)}
        )

    errs.extend(check_manifest(candidates_dir, candidate_files, existing))
    summary["issues"] = errs
    summary["status"] = "fail" if errs else "pass"
    return errs, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--json", action="store_true", help="print machine-readable summary")
    args = parser.parse_args(argv)

    if not args.candidates_dir.exists():
        print(f"candidates directory not found: {args.candidates_dir}", file=sys.stderr)
        return 2

    errs, summary = run(args.candidates_dir, args.migrations_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"Candidates: {len(summary.get('candidates', []))}; "
            f"existing max V{summary.get('existing_max_version', 0)}"
        )
        for item in summary.get("candidates", []):
            print(f"  V{item['version']}: {item['filename']} sha256={item['sha256'][:12]}…")
        for err in errs:
            print(f"FAIL: {err}")
        print(
            "Result: PASS (candidates consistent; NOT approved/applied)"
            if not errs
            else f"Result: FAIL ({len(errs)} issue(s))"
        )
    return 0 if not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
