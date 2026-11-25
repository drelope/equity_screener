"""Rehearse P0 additive SQL drafts on an explicitly provided disposable database.

Safety: refuses to run without --dsn, refuses DSN from environment/config, and
requires --i-understand-disposable-target for --apply. Drafts are NOT applied to
the shared/default database by this script. Intended for isolated disposable
Postgres instances only (e.g. docker run postgres:17-alpine).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DRAFTS_DIR = (
    PROJECT_ROOT / "docs" / "speckit-recovery" / "08-implementation-validation" / "sql-drafts"
)
DEFAULT_DRAFTS = [
    "rm01_pit_membership_additive.sql",
    "rm02_pit_timing_additive.sql",
    "rm03_dividend_evidence_quarantine.sql",
    "rm04_run_manifest_ledger.sql",
]

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def discover_drafts(names: list[str] | None = None) -> list[Path]:
    wanted = names or DEFAULT_DRAFTS
    paths = []
    for name in wanted:
        path = DRAFTS_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"draft not found: {path}")
        paths.append(path)
    return paths


def safety_check_dsn(dsn: str, allow_nonlocal: bool) -> list[str]:
    issues = []
    try:
        url = make_url(dsn)
    except Exception as exc:  # noqa: BLE001
        return [f"invalid DSN: {exc}"]
    host = (url.host or "").lower()
    if not host:
        issues.append("DSN host is missing")
    elif host not in LOCAL_HOSTS and not allow_nonlocal:
        issues.append(
            f"DSN host {host!r} is non-local; pass --allow-nonlocal only for an isolated disposable target"
        )
    db = (url.database or "").lower()
    if db in {"dividend", "prod", "production"} and not allow_nonlocal:
        issues.append(
            f"DSN database name {url.database!r} looks shared/production-like; refuse without --allow-nonlocal"
        )
    return issues


def split_statements(sql_text: str) -> list[str]:
    statements = []
    current = []
    in_string = False
    dollar_quote = None
    i = 0
    while i < len(sql_text):
        ch = sql_text[i]
        if dollar_quote is not None:
            if sql_text.startswith(dollar_quote, i):
                current.append(dollar_quote)
                i += len(dollar_quote) - 1
                dollar_quote = None
            else:
                current.append(ch)
        elif ch == "'":
            if in_string and i + 1 < len(sql_text) and sql_text[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_string = not in_string
                current.append(ch)
        elif not in_string and ch == "$":
            m = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql_text[i:])
            if m:
                dollar_quote = m.group(0)
                current.append(dollar_quote)
                i += len(dollar_quote) - 1
            else:
                current.append(ch)
        elif not in_string and sql_text.startswith("--", i):
            nl = sql_text.find("\n", i)
            if nl == -1:
                break
            if current:
                current.append(" ")
            i = nl
        elif not in_string and sql_text.startswith("/*", i):
            end = sql_text.find("*/", i + 2)
            if end == -1:
                break
            current.append(" ")
            i = end + 2
        elif ch == ";" and not in_string:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def verify_objects(conn) -> dict[str, bool]:
    checks = {
        "reference.security_membership_history": "to_regclass('reference.security_membership_history') IS NOT NULL",
        "reference.security_eligibility_asof": "to_regclass('reference.security_eligibility_asof') IS NOT NULL",
        "raw.dividend_data_evidence": "to_regclass('raw.dividend_data_evidence') IS NOT NULL",
        "audit.dividend_quarantine": "to_regclass('audit.dividend_quarantine') IS NOT NULL",
        "audit.dividend_corrections": "to_regclass('audit.dividend_corrections') IS NOT NULL",
        "audit.run_manifests": "to_regclass('audit.run_manifests') IS NOT NULL",
        "audit.run_outputs": "to_regclass('audit.run_outputs') IS NOT NULL",
    }
    results = {}
    for name, expr in checks.items():
        try:
            results[name] = bool(conn.execute(text(f"SELECT {expr}")).scalar())
        except Exception:  # noqa: BLE001
            results[name] = False
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", help="Explicit SQLAlchemy/Postgres DSN for disposable target")
    p.add_argument("--draft", action="append", help="Draft filename(s) from sql-drafts/")
    p.add_argument(
        "--check-only", action="store_true", help="Validate draft files and DSN safety only"
    )
    p.add_argument("--apply", action="store_true", help="Apply drafts to disposable target")
    p.add_argument("--verify", action="store_true", help="Run post-apply object checks")
    p.add_argument(
        "--allow-nonlocal", action="store_true", help="Allow non-local/non-obvious DSN (dangerous)"
    )
    p.add_argument(
        "--i-understand-disposable-target",
        action="store_true",
        help="Required with --apply to confirm target is isolated/disposable",
    )
    p.add_argument("--out", type=Path, help="Write JSON summary to this path")
    args = p.parse_args(argv)

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "drafts_dir": str(DRAFTS_DIR),
        "drafts": [],
        "applied": [],
        "errors": [],
        "status": "started",
    }

    try:
        drafts = discover_drafts(args.draft)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for path in drafts:
        content = path.read_text(encoding="utf-8")
        stmts = split_statements(content)
        summary["drafts"].append(
            {
                "name": path.name,
                "path": str(path),
                "sha256": sha256_text(content),
                "statements": len(stmts),
            }
        )
        print(
            f"draft: {path.name} ({len(stmts)} statements, sha256={sha256_text(content)[:12]}...)"
        )

    if not args.dsn:
        summary["status"] = "check_only_no_dsn" if args.check_only else "missing_dsn"
        if args.apply or args.verify:
            print("ERROR: --dsn is required for --apply/--verify", file=sys.stderr)
            return 2
        print("No --dsn provided; file checks only.")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0

    issues = safety_check_dsn(args.dsn, args.allow_nonlocal)
    summary["dsn_safety_issues"] = issues
    for issue in issues:
        print(f"SAFETY: {issue}", file=sys.stderr)
    if issues:
        summary["status"] = "dsn_safety_failed"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 2

    if args.check_only and not args.apply:
        summary["status"] = "check_only_ok"
        print("DSN safety checks passed (no apply).")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0

    if args.apply and not args.i_understand_disposable_target:
        print("ERROR: --apply requires --i-understand-disposable-target", file=sys.stderr)
        summary["status"] = "apply_confirmation_missing"
        return 2

    engine = create_engine(args.dsn)
    try:
        with engine.begin() as conn:
            for path in drafts:
                sql_text = path.read_text(encoding="utf-8")
                if args.apply:
                    conn.execute(text(sql_text))
                    summary["applied"].append(path.name)
                    print(f"applied: {path.name}")
        if args.verify or args.apply:
            with engine.connect() as conn:
                summary["verification"] = verify_objects(conn)
                print("verification:", json.dumps(summary["verification"], sort_keys=True))
        summary["status"] = "applied" if args.apply else "verified"
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(str(exc))
        summary["status"] = "failed"
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 1
    finally:
        engine.dispose()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
