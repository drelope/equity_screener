"""Baseline-aware disposable rehearsal for P0 SQL drafts/candidates.

Bootstraps an explicitly provided disposable Postgres database with:
  1) sql/schema.sql
  2) scripts/init_db.py inline compatibility migrations (parsed, not imported)
  3) versioned sql/migrations/V*.sql in order (ledger-tracked)
  4) optional additive draft/candidate SQL files (default: docs/.../sql-drafts;
     pass --drafts-dir docs/.../sql-candidates to rehearse numbered candidates)
  5) optional --rollback: apply V<version>_rollback.sql in reverse order and
     verify the candidate objects are gone (disposable targets only)

Safety: explicit --dsn required; refuses obvious shared/local-prod names unless
--allow-nonlocal/--allow-shared-name; --apply requires --i-understand-disposable-target.
No writes to default DATABASE_URL or shared project DB.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate import (  # noqa: E402
    apply_migration,
    discover_migrations,
    ensure_tracking_table,
)

SCHEMA_SQL = PROJECT_ROOT / "sql" / "schema.sql"
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


def split_statements(sql_text: str) -> list[str]:
    """Split SQL on terminators, respecting quotes, dollar-quotes and comments."""
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


def init_db_inline_migrations(path: Path | None = None) -> list[str]:
    path = path or PROJECT_ROOT / "scripts" / "init_db.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "migrations" for target in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise RuntimeError(f"no `migrations` list found in {path}")


def safety_check_dsn(dsn: str, allow_nonlocal: bool, allow_shared_name: bool) -> list[str]:
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
            f"DSN host {host!r} is non-local; pass --allow-nonlocal only for isolated disposable target"
        )
    db = (url.database or "").lower()
    if db in {"dividend", "prod", "production", "dividend_equity"} and not allow_shared_name:
        issues.append(
            f"DSN database name {url.database!r} looks shared/production-like; refuse without --allow-shared-name"
        )
    return issues


def apply_sql_text(conn, sql_text: str) -> int:
    count = 0
    for stmt in split_statements(sql_text):
        conn.execute(text(stmt))
        count += 1
    return count


def apply_schema(conn) -> dict:
    content = SCHEMA_SQL.read_text(encoding="utf-8")
    count = apply_sql_text(conn, content)
    return {"file": "sql/schema.sql", "sha256": sha256_text(content), "statements": count}


def apply_init_inline(conn) -> dict:
    migrations = init_db_inline_migrations()
    total = 0
    for mig in migrations:
        total += apply_sql_text(conn, mig)
    joined = "\n---\n".join(migrations)
    return {
        "file": "scripts/init_db.py#migrations",
        "count": len(migrations),
        "statements": total,
        "sha256": sha256_text(joined),
    }


def apply_versioned(conn, summary: dict) -> dict:
    ensure_tracking_table(conn)
    applied_rows = conn.execute(
        text("SELECT version, name FROM public.schema_migrations ORDER BY version")
    ).fetchall()
    applied = {row[0]: row[1] for row in applied_rows}
    if 1 not in applied:
        conn.execute(
            text(
                "INSERT INTO public.schema_migrations (version, name) "
                "VALUES (1, 'baseline: schema.sql + init_db inline migrations (rehearsal)') "
                "ON CONFLICT (version) DO NOTHING"
            )
        )
        applied[1] = "baseline"

    migrations = discover_migrations()
    applied_now = []
    for version, name, sql_text in migrations:
        if version in applied:
            continue
        apply_migration(conn, version, name, sql_text)
        applied_now.append({"version": version, "name": name, "sha256": sha256_text(sql_text)})
    return {
        "available": len(migrations),
        "applied_now": applied_now,
        "applied_total_after": len(applied) + len(applied_now),
    }


def discover_drafts(names: list[str] | None = None, drafts_dir: Path | None = None) -> list[Path]:
    base = drafts_dir or DRAFTS_DIR
    if names is None and drafts_dir is not None:
        paths = sorted(base.glob("V*.sql"))
        if not paths:
            raise FileNotFoundError(f"no V*.sql candidates found in {base}")
        return paths
    wanted = names or DEFAULT_DRAFTS
    paths = []
    for name in wanted:
        path = base / name
        if not path.exists():
            raise FileNotFoundError(f"draft not found: {path}")
        paths.append(path)
    return paths


def discover_rollbacks(drafts: list[Path], rollback_dir: Path | None = None) -> list[Path]:
    """Resolve ``V<version>_rollback.sql`` for each numbered candidate draft."""
    base = rollback_dir or (drafts[0].parent / "rollback" if drafts else None)
    if base is None:
        raise FileNotFoundError("no drafts to derive rollback directory from")
    paths = []
    for draft in drafts:
        match = re.match(r"^V(\d+)_.*\.sql$", draft.name)
        if not match:
            raise FileNotFoundError(f"cannot derive rollback version from {draft.name!r}")
        path = base / f"V{match.group(1)}_rollback.sql"
        if not path.exists():
            raise FileNotFoundError(f"rollback not found: {path}")
        paths.append(path)
    return paths


def verify_objects(conn, expected_versions: set[int] | None = None) -> dict[str, bool]:
    checks = {
        "reference.security_membership_history": "to_regclass('reference.security_membership_history') IS NOT NULL",
        "reference.security_eligibility_asof": "to_regclass('reference.security_eligibility_asof') IS NOT NULL",
        "reference.securities.delisted_date": """
            EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_schema='reference' AND table_name='securities' AND column_name='delisted_date'
            )
        """,
        "raw.dividend_data_evidence": "to_regclass('raw.dividend_data_evidence') IS NOT NULL",
        "audit.dividend_quarantine": "to_regclass('audit.dividend_quarantine') IS NOT NULL",
        "audit.dividend_corrections": "to_regclass('audit.dividend_corrections') IS NOT NULL",
        "audit.run_manifests": "to_regclass('audit.run_manifests') IS NOT NULL",
        "audit.run_outputs": "to_regclass('audit.run_outputs') IS NOT NULL",
        "audit.run_manifests_append_only": """
            EXISTS (
              SELECT 1 FROM pg_trigger
              WHERE tgname='run_manifests_append_only'
                AND tgrelid=to_regclass('audit.run_manifests')
                AND NOT tgisinternal
            )
        """,
        "audit.run_outputs_append_only": """
            EXISTS (
              SELECT 1 FROM pg_trigger
              WHERE tgname='run_outputs_append_only'
                AND tgrelid=to_regclass('audit.run_outputs')
                AND NOT tgisinternal
            )
        """,
        "public.schema_migrations": "to_regclass('public.schema_migrations') IS NOT NULL",
    }
    versions = set(expected_versions or ())
    if 112 in versions:
        checks.update(
            {
                "V0112.manifest_writer.insert": (
                    "has_table_privilege('manifest_writer', 'audit.run_manifests', 'INSERT')"
                ),
                "V0112.manifest_reader.select": (
                    "has_table_privilege('manifest_reader', 'audit.run_outputs', 'SELECT')"
                ),
                "V0112.ledger_auditor.schema_migrations.select": (
                    "has_table_privilege('ledger_auditor', 'public.schema_migrations', 'SELECT')"
                ),
            }
        )
    if 113 in versions:
        checks.update(
            {
                "audit.ledger_governance_events": (
                    "to_regclass('audit.ledger_governance_events') IS NOT NULL"
                ),
                "audit.ledger_governance_events_append_only": """
                    EXISTS (
                      SELECT 1 FROM pg_trigger
                      WHERE tgname='ledger_governance_events_append_only'
                        AND tgrelid=to_regclass('audit.ledger_governance_events')
                        AND NOT tgisinternal
                    )
                """,
            }
        )
    results = {}
    for name, expr in checks.items():
        try:
            results[name] = bool(conn.execute(text(f"SELECT ({expr})")).scalar())
        except Exception:  # noqa: BLE001
            results[name] = False
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", help="Explicit disposable database DSN")
    p.add_argument("--draft", action="append", help="Draft filename(s)")
    p.add_argument(
        "--drafts-dir", type=Path, help="Directory containing draft files (default: sql-drafts)"
    )
    p.add_argument(
        "--rollback",
        action="store_true",
        help="After apply/verify, run V<version>_rollback.sql for each numbered draft (disposable only)",
    )
    p.add_argument(
        "--rollback-dir",
        type=Path,
        help="Directory containing rollback files (default: <drafts-dir>/rollback)",
    )
    p.add_argument("--check-only", action="store_true", help="Validate files/DSN safety only")
    p.add_argument("--apply", action="store_true", help="Apply baseline + drafts")
    p.add_argument("--baseline-only", action="store_true", help="Apply baseline only (skip drafts)")
    p.add_argument(
        "--skip-versioned-migrations", action="store_true", help="Skip sql/migrations/V* apply"
    )
    p.add_argument("--verify", action="store_true", help="Run post-apply verification queries")
    p.add_argument("--allow-nonlocal", action="store_true")
    p.add_argument("--allow-shared-name", action="store_true")
    p.add_argument("--i-understand-disposable-target", action="store_true")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "started",
        "phases": {},
        "drafts": [],
        "errors": [],
    }

    try:
        drafts = discover_drafts(args.draft, args.drafts_dir)
        rollbacks = discover_rollbacks(drafts, args.rollback_dir) if args.rollback else []
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in drafts:
        content = path.read_text(encoding="utf-8")
        summary["drafts"].append(
            {
                "name": path.name,
                "sha256": sha256_text(content),
                "statements": len(split_statements(content)),
            }
        )
    summary["rollbacks"] = []
    for path in rollbacks:
        content = path.read_text(encoding="utf-8")
        summary["rollbacks"].append(
            {
                "name": path.name,
                "sha256": sha256_text(content),
                "statements": len(split_statements(content)),
            }
        )

    schema_content = SCHEMA_SQL.read_text(encoding="utf-8")
    print(f"schema: sql/schema.sql ({len(split_statements(schema_content))} statements)")
    print(f"init_db inline migrations: {len(init_db_inline_migrations())}")
    print(f"versioned migrations available: {len(discover_migrations())}")
    for d in summary["drafts"]:
        print(f"draft: {d['name']} ({d['statements']} statements, sha256={d['sha256'][:12]}...)")
    for r in summary["rollbacks"]:
        print(f"rollback: {r['name']} ({r['statements']} statements, sha256={r['sha256'][:12]}...)")

    if not args.dsn:
        summary["status"] = "check_only_no_dsn"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("No --dsn provided; file checks only.")
        return 0

    issues = safety_check_dsn(args.dsn, args.allow_nonlocal, args.allow_shared_name)
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

    if not args.apply:
        print("No --apply specified; nothing to execute.")
        summary["status"] = "no_apply"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0

    if not args.i_understand_disposable_target:
        print("ERROR: --apply requires --i-understand-disposable-target", file=sys.stderr)
        summary["status"] = "apply_confirmation_missing"
        return 2

    engine = create_engine(args.dsn)
    try:
        with engine.begin() as conn:
            summary["phases"]["schema"] = apply_schema(conn)
            print("applied: sql/schema.sql")
            summary["phases"]["init_inline"] = apply_init_inline(conn)
            print("applied: init_db inline migrations")
            if not args.skip_versioned_migrations:
                summary["phases"]["versioned_migrations"] = apply_versioned(conn, summary)
                vm = summary["phases"]["versioned_migrations"]
                print(f"applied: {len(vm['applied_now'])} versioned migrations")
            else:
                summary["phases"]["versioned_migrations"] = {"skipped": True}
            summary["phases"]["drafts_applied"] = []
            if not args.baseline_only:
                for path in drafts:
                    content = path.read_text(encoding="utf-8")
                    conn.execute(text(content))
                    summary["phases"]["drafts_applied"].append(path.name)
                    print(f"applied draft: {path.name}")
        candidate_versions = {
            int(match.group(1))
            for path in drafts
            if (match := re.match(r"^V(\d+)_.*\.sql$", path.name))
        }
        if args.verify or not args.baseline_only:
            with engine.connect() as conn:
                summary["verification"] = verify_objects(conn, candidate_versions)
                print("verification:", json.dumps(summary["verification"], sort_keys=True))
        if rollbacks:
            summary["phases"]["rollbacks_applied"] = []
            for path in reversed(rollbacks):
                content = path.read_text(encoding="utf-8")
                with engine.begin() as conn:
                    conn.execute(text(content))
                summary["phases"]["rollbacks_applied"].append(path.name)
                print(f"applied rollback: {path.name}")
            with engine.connect() as conn:
                after = verify_objects(conn, candidate_versions)
                summary["rollback_verification"] = after
                print("rollback verification:", json.dumps(after, sort_keys=True))
                expected_absent = [name for name in after if name != "public.schema_migrations"]
                leftovers = [name for name in expected_absent if after[name]]
                if leftovers:
                    raise RuntimeError(f"rollback left objects present: {', '.join(leftovers)}")
                if not after.get("public.schema_migrations"):
                    raise RuntimeError("rollback removed public.schema_migrations unexpectedly")
            summary["status"] = "applied_and_rolled_back"
        else:
            summary["status"] = "applied"
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(str(exc))
        summary["status"] = "failed"
        print(f"ERROR: {exc}", file=sys.stderr)
    finally:
        engine.dispose()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["status"] in {"applied", "applied_and_rolled_back"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
