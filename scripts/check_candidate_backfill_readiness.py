"""Read-only backfill/reconciliation readiness checks for numbered candidates.

Without ``--dsn`` this runs static checks only (candidate manifest/hashes and the
candidate checker). With an explicit ``--dsn`` it opens a **read-only**
transaction, verifies the candidate objects/columns exist, and runs aggregate
queries that report backfill coverage and anomalies for V0107–V0110.

Safety: refuses obvious shared/production database names unless
``--allow-shared-name``; never writes. Exit codes:
  0 = static checks pass / all candidate checks passed
  1 = candidate schema missing, backfill incomplete, or anomalies found
  2 = usage, safety refusal, or database error

This tool does not approve, apply, backfill, or promote anything. It only reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_migration_candidates import (  # noqa: E402
    DEFAULT_CANDIDATES_DIR,
    DEFAULT_MIGRATIONS_DIR,
)
from scripts.check_migration_candidates import (  # noqa: E402
    run as run_candidate_checker,
)
from scripts.rehearse_p0_full import safety_check_dsn  # noqa: E402

TABLE_OBJECT = "table"
COLUMN_OBJECT = "column"

CANDIDATES: dict[int, dict] = {
    107: {
        "name": "RM-01 PIT membership",
        "primary_count": "membership_rows",
        "objects": [
            (TABLE_OBJECT, "reference.security_membership_history"),
            (TABLE_OBJECT, "reference.security_eligibility_asof"),
            (COLUMN_OBJECT, "reference.securities", "delisted_date"),
        ],
        "checks": [
            ("membership_rows", "SELECT count(*) FROM reference.security_membership_history", None),
            ("securities_total", "SELECT count(*) FROM reference.securities", None),
            (
                "securities_with_delisted_date",
                "SELECT count(*) FROM reference.securities WHERE delisted_date IS NOT NULL",
                None,
            ),
            (
                "inactive_securities",
                "SELECT count(*) FROM reference.securities WHERE active IS FALSE",
                None,
            ),
            (
                "inactive_without_delisted_date",
                "SELECT count(*) FROM reference.securities "
                "WHERE active IS FALSE AND delisted_date IS NULL",
                (
                    "positive",
                    "inactive securities without delisted_date (backfill incomplete or unknown)",
                ),
            ),
            (
                "open_membership_intervals",
                "SELECT count(*) FROM reference.security_membership_history WHERE effective_to IS NULL",
                None,
            ),
            (
                "overlapping_membership_pairs",
                """
                SELECT count(*) FROM (
                  SELECT security_id, effective_from, effective_to,
                         LAG(effective_to) OVER (
                           PARTITION BY security_id ORDER BY effective_from
                         ) AS prev_to,
                         ROW_NUMBER() OVER (
                           PARTITION BY security_id ORDER BY effective_from
                         ) AS rn
                  FROM reference.security_membership_history
                ) t
                WHERE rn > 1 AND (prev_to IS NULL OR effective_from <= prev_to)
                """,
                ("positive", "overlapping membership intervals"),
            ),
            (
                "eligibility_rows",
                "SELECT count(*) FROM reference.security_eligibility_asof",
                None,
            ),
        ],
    },
    108: {
        "name": "RM-02 PIT timing",
        "primary_count": "dividend_rows",
        "objects": [
            (COLUMN_OBJECT, "raw.dividend_data", "declared_known_at"),
            (COLUMN_OBJECT, "raw.dividend_data", "record_known_at"),
            (COLUMN_OBJECT, "raw.dividend_data", "payment_known_at"),
            (COLUMN_OBJECT, "raw.dividend_data", "ex_known_at"),
            (COLUMN_OBJECT, "raw.dividend_data", "available_at"),
            (COLUMN_OBJECT, "raw.dividend_data", "timing_evidence_source"),
            (COLUMN_OBJECT, "raw.dividend_data", "timing_confidence"),
        ],
        "checks": [
            ("dividend_rows", "SELECT count(*) FROM raw.dividend_data", None),
            (
                "rows_with_available_at",
                "SELECT count(*) FROM raw.dividend_data WHERE available_at IS NOT NULL",
                None,
            ),
            (
                "rows_with_ex_known_at",
                "SELECT count(*) FROM raw.dividend_data WHERE ex_known_at IS NOT NULL",
                None,
            ),
            (
                "rows_with_any_known_at",
                "SELECT count(*) FROM raw.dividend_data WHERE "
                "declared_known_at IS NOT NULL OR record_known_at IS NOT NULL OR "
                "payment_known_at IS NOT NULL OR ex_known_at IS NOT NULL",
                None,
            ),
            (
                "available_before_ex_date",
                "SELECT count(*) FROM raw.dividend_data "
                "WHERE available_at IS NOT NULL AND ex_dividend_date IS NOT NULL "
                "AND available_at::date < ex_dividend_date",
                ("positive", "availability timestamp precedes the ex-dividend date"),
            ),
            (
                "available_without_evidence_source",
                "SELECT count(*) FROM raw.dividend_data "
                "WHERE available_at IS NOT NULL AND timing_evidence_source IS NULL",
                ("positive", "availability rows missing timing_evidence_source"),
            ),
            (
                "known_at_after_retrieval",
                "SELECT count(*) FROM raw.dividend_data "
                "WHERE ex_known_at IS NOT NULL AND ex_known_at > retrieved_at",
                ("positive", "ex_known_at later than retrieval time"),
            ),
            (
                "no_availability_backfill",
                "SELECT count(*) FROM raw.dividend_data WHERE available_at IS NULL",
                ("all_rows", "no available_at backfill (all dividend rows NULL)"),
            ),
        ],
    },
    109: {
        "name": "RM-03 dividend evidence/quarantine",
        "primary_count": "evidence_rows",
        "objects": [
            (TABLE_OBJECT, "raw.dividend_data_evidence"),
            (TABLE_OBJECT, "audit.dividend_quarantine"),
            (TABLE_OBJECT, "audit.dividend_corrections"),
        ],
        "checks": [
            ("evidence_rows", "SELECT count(*) FROM raw.dividend_data_evidence", None),
            ("raw_dividend_rows", "SELECT count(*) FROM raw.dividend_data", None),
            (
                "quarantined_evidence_rows",
                "SELECT count(*) FROM raw.dividend_data_evidence WHERE is_quarantined IS TRUE",
                None,
            ),
            (
                "open_quarantine_rows",
                "SELECT count(*) FROM audit.dividend_quarantine WHERE status = 'open'",
                None,
            ),
            (
                "quarantine_without_evidence",
                "SELECT count(*) FROM audit.dividend_quarantine WHERE evidence_id IS NULL",
                ("positive", "quarantine rows without evidence linkage (legacy rows need review)"),
            ),
            (
                "correction_rows",
                "SELECT count(*) FROM audit.dividend_corrections",
                None,
            ),
            (
                "corrections_without_evidence",
                "SELECT count(*) FROM audit.dividend_corrections WHERE source_evidence_id IS NULL",
                ("positive", "correction rows without source evidence linkage"),
            ),
            (
                "duplicate_source_event_groups",
                """
                SELECT count(*) FROM (
                  SELECT provider, feed, source_event_key
                  FROM raw.dividend_data_evidence
                  WHERE source_event_key IS NOT NULL
                  GROUP BY provider, feed, source_event_key
                  HAVING count(*) > 1
                ) d
                """,
                ("positive", "duplicate provider/feed/source_event_key evidence groups"),
            ),
        ],
    },
    110: {
        "name": "RM-04/RM-05 run manifest ledger",
        "primary_count": "manifest_rows",
        "objects": [
            (TABLE_OBJECT, "audit.run_manifests"),
            (TABLE_OBJECT, "audit.run_outputs"),
        ],
        "checks": [
            ("manifest_rows", "SELECT count(*) FROM audit.run_manifests", None),
            ("output_rows", "SELECT count(*) FROM audit.run_outputs", None),
            (
                "manifests_missing_hash",
                "SELECT count(*) FROM audit.run_manifests "
                "WHERE manifest_hash IS NULL OR manifest_hash = ''",
                ("positive", "run manifests missing manifest_hash"),
            ),
            (
                "manifests_missing_json",
                "SELECT count(*) FROM audit.run_manifests WHERE manifest_json IS NULL",
                ("positive", "run manifests missing manifest_json"),
            ),
            (
                "outputs_without_storage_ref",
                "SELECT count(*) FROM audit.run_outputs "
                "WHERE storage_ref IS NULL OR storage_ref = ''",
                ("positive", "run outputs missing storage_ref"),
            ),
            (
                "outputs_without_content_hash",
                "SELECT count(*) FROM audit.run_outputs WHERE content_hash IS NULL",
                None,
            ),
        ],
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def render_sql() -> str:
    """Render the canonical read-only check catalog for DBA/ops review."""
    lines = [
        "-- CANDIDATE BACKFILL READINESS CHECKS: READ-ONLY / NOT APPLIED",
        "-- Generated from scripts/check_candidate_backfill_readiness.py.",
        "-- Run inside a READ ONLY transaction against an approved target only.",
        "",
    ]
    for version, spec in CANDIDATES.items():
        lines.append(f"-- V{version:04d}: {spec['name']} (primary count: {spec['primary_count']})")
        for key, sql, issue in spec["checks"]:
            lines.append(f"-- check: {key}")
            if issue:
                lines.append(f"-- issue when {issue[0]}: {issue[1]}")
            lines.append(sql.strip().rstrip(";") + ";")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def object_exists(conn, kind: str, *parts: str) -> bool:
    if kind == TABLE_OBJECT:
        if len(parts) == 1:
            schema, table = parts[0].rsplit(".", 1)
        else:
            schema, table = parts
        row = conn.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"{schema}.{table}"},
        ).scalar()
        return bool(row)
    if kind == COLUMN_OBJECT:
        if len(parts) == 2:
            schema_table, column = parts
            schema, table = schema_table.rsplit(".", 1)
        else:
            schema, table, column = parts
        row = conn.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_schema = :schema
                    AND table_name = :table
                    AND column_name = :column
                )
                """
            ),
            {"schema": schema, "table": table, "column": column},
        ).scalar()
        return bool(row)
    raise ValueError(f"unknown object kind: {kind}")


def _issue_condition(kind: str, value: int, check: dict) -> bool:
    if kind == "positive":
        return value > 0
    if kind == "zero":
        return value == 0
    if kind == "all_rows":
        return value == check.get("primary_total", 0) and value > 0
    raise ValueError(f"unknown issue condition: {kind}")


def evaluate_candidate(conn, version: int, spec: dict) -> dict:
    result: dict = {
        "version": version,
        "name": spec["name"],
        "objects_present": True,
        "missing_objects": [],
        "schema_status": "present",
        "data_status": "unknown",
        "checks": {},
        "check_errors": {},
        "issues": [],
    }
    for obj in spec["objects"]:
        if not object_exists(conn, *obj):
            result["objects_present"] = False
            result["missing_objects"].append(".".join(obj[1:]))
    if not result["objects_present"]:
        result["schema_status"] = "not_applied"
        result["data_status"] = "unknown"
        return result

    for key, sql, issue in spec["checks"]:
        try:
            value = conn.execute(text(sql)).scalar()
        except Exception as exc:  # noqa: BLE001
            result["checks"][key] = None
            result["check_errors"][key] = str(exc)
            result["issues"].append(f"{key}: query failed: {exc}")
            continue
        value = int(value or 0)
        result["checks"][key] = value
        if issue:
            kind, message = issue
            candidate_issue = {"kind": kind, "message": message, "value": value}
            if kind == "all_rows":
                primary_total = result["checks"].get(spec["primary_count"], 0)
                candidate_issue["primary_total"] = primary_total
                if primary_total and value >= primary_total:
                    result["issues"].append(message)
            elif _issue_condition(kind, value, candidate_issue):
                result["issues"].append(message)

    primary_total = int(result["checks"].get(spec["primary_count"], 0) or 0)
    if primary_total == 0:
        result["data_status"] = "no_data"
        result["issues"].append(f"{spec['primary_count']} is zero (backfill not started)")
    elif result["issues"]:
        result["data_status"] = "attention_required"
    else:
        result["data_status"] = "checks_passed"
    return result


def run_static(
    candidates_dir: Path = DEFAULT_CANDIDATES_DIR, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
) -> dict:
    errs, summary = run_candidate_checker(candidates_dir, migrations_dir)
    return {
        "mode": "static",
        "status": "pass" if not errs else "fail",
        "issues": errs,
        "candidate_versions": summary.get("candidate_versions", []),
        "existing_max_version": summary.get("existing_max_version"),
    }


def sanitized_target(dsn: str) -> dict:
    url = make_url(dsn)
    return {"host": url.host, "database": url.database, "driver": url.drivername}


def run_readonly(dsn: str, allow_nonlocal: bool, allow_shared_name: bool) -> dict:
    issues = safety_check_dsn(dsn, allow_nonlocal, allow_shared_name)
    if issues:
        return {"mode": "read_only", "status": "safety_refused", "issues": issues}

    engine = create_engine(dsn)
    report: dict = {
        "mode": "read_only",
        "status": "unknown",
        "target": sanitized_target(dsn),
        "candidates": {},
        "issues": [],
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '60s'"))
            for version, spec in CANDIDATES.items():
                report["candidates"][str(version)] = evaluate_candidate(conn, version, spec)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "database_error"
        report["issues"].append(str(exc))
        return report
    finally:
        engine.dispose()

    missing = [
        f"V{version}: schema not applied ({', '.join(c['missing_objects'])})"
        for version, c in report["candidates"].items()
        if c["schema_status"] != "present"
    ]
    attention = [
        f"V{version}: {issue}"
        for version, c in report["candidates"].items()
        for issue in c["issues"]
    ]
    report["issues"] = missing + attention
    if missing:
        report["status"] = "not_ready_schema_missing"
    elif any(c["data_status"] == "no_data" for c in report["candidates"].values()):
        report["status"] = "not_ready_no_backfill_data"
    elif attention:
        report["status"] = "attention_required"
    else:
        report["status"] = "checks_passed"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="Explicit database DSN for read-only checks")
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--allow-shared-name", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--json", action="store_true", help="print machine-readable report")
    parser.add_argument(
        "--print-sql", action="store_true", help="print the read-only check catalog"
    )
    args = parser.parse_args(argv)

    if args.print_sql:
        print(render_sql(), end="")
        return 0
    if args.dsn:
        report = run_readonly(args.dsn, args.allow_nonlocal, args.allow_shared_name)
    else:
        report = run_static()
    report["generated_at_utc"] = utc_now()
    report["read_only"] = True

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"mode={report.get('mode')} status={report.get('status')} read_only=True")
        if report.get("target"):
            print(f"target: {report['target']['host']}/{report['target']['database']}")
        for version, candidate in report.get("candidates", {}).items():
            print(
                f"  V{int(version):04d} {candidate['name']}: "
                f"schema={candidate['schema_status']} data={candidate['data_status']}"
            )
            for issue in candidate["issues"]:
                print(f"    - {issue}")
        if report.get("mode") == "static" or report["status"] in {
            "safety_refused",
            "database_error",
        }:
            for issue in report.get("issues", []):
                print(f"FAIL: {issue}")
        if report["status"] == "pass":
            print("Result: PASS (static checks only)")
        elif report["status"] == "checks_passed":
            print("Result: PASS (read-only readiness checks; not promotion evidence)")
        else:
            print(f"Result: {report['status'].upper()}")

    if report["status"] == "pass":
        return 0
    if report["status"] == "checks_passed":
        return 0
    if report["status"] in {"safety_refused", "database_error"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
