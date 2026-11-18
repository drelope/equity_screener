"""Validate the draft manifest-ledger role/retention/incident-response policy.

This is governance scaffolding for the V0110/V0111 candidate ledger. It validates
structure and safety invariants only; it does not grant roles, change a database,
approve policy, or prove operational enforcement. Exit 0 = structure/invariants pass
(draft or approved); exit 1 = issues or ``--require-approved`` unmet; exit 2 = usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = (
    PROJECT_ROOT
    / "docs"
    / "speckit-recovery"
    / "08-implementation-validation"
    / "manifest-ledger-governance-policy-template.json"
)

REQUIRED_SCHEMA = "manifest_ledger_governance/v1"
VALID_STATUS = {"draft_not_approved", "approved"}
REQUIRED_TABLES = {"audit.run_manifests", "audit.run_outputs"}
REQUIRED_ROLES = {"manifest_writer", "manifest_reader", "ledger_auditor", "dba_admin"}
REQUIRED_APPROVALS = ("M1", "DEC-002", "DEC-003", "DEC-005")
WRITER_REQUIRED_PRIVS = {"INSERT"}
WRITER_FORBIDDEN = {"UPDATE", "DELETE", "TRUNCATE"}
READER_REQUIRED_PRIVS = {"SELECT"}
READER_FORBIDDEN = {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}
SEQUENCE_RE = re.compile(r"_seq$", re.IGNORECASE)


def _privs(grant: dict) -> set[str]:
    values = grant.get("privileges", [])
    if not isinstance(values, list):
        return set()
    return {str(value).upper() for value in values if isinstance(value, str)}


def _grants_for(role: dict, table: str) -> list[set[str]]:
    grants = role.get("grants", [])
    if not isinstance(grants, list):
        return []
    return [
        _privs(grant)
        for grant in grants
        if isinstance(grant, dict) and str(grant.get("table", "")).strip() == table
    ]


def _role_has_priv(role: dict, table: str, privilege: str) -> bool:
    return any(privilege in privs for privs in _grants_for(role, table))


def _role_has_forbidden(role: dict, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    grants = role.get("grants", [])
    if not isinstance(grants, list):
        return found
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        found.update(_privs(grant) & forbidden)
    return found


def check_policy(policy) -> list[str]:
    errs: list[str] = []
    if not isinstance(policy, dict):
        return ["policy must be a JSON object"]
    if policy.get("schema") != REQUIRED_SCHEMA:
        errs.append(f"schema must be {REQUIRED_SCHEMA!r}")
    status = policy.get("status")
    if status not in VALID_STATUS:
        errs.append(f"status must be one of {sorted(VALID_STATUS)}")

    tables = policy.get("ledger_tables")
    if not isinstance(tables, list) or not REQUIRED_TABLES.issubset({str(t) for t in tables}):
        errs.append("ledger_tables must include audit.run_manifests and audit.run_outputs")
    if policy.get("public_privileges") != []:
        errs.append("public_privileges must be an empty list (no PUBLIC grants)")

    roles = policy.get("roles")
    if not isinstance(roles, dict):
        return errs + ["roles must be an object"]
    missing_roles = sorted(REQUIRED_ROLES - set(roles))
    if missing_roles:
        errs.append(f"missing required roles: {', '.join(missing_roles)}")

    writer = roles.get("manifest_writer")
    if not isinstance(writer, dict):
        errs.append("manifest_writer must be an object")
    else:
        for table in REQUIRED_TABLES:
            if not _role_has_priv(writer, table, "INSERT"):
                errs.append(f"manifest_writer must have INSERT on {table}")
        sequence_grants = [
            _privs(grant)
            for grant in writer.get("grants", [])
            if isinstance(grant, dict) and SEQUENCE_RE.search(str(grant.get("table", "")))
        ]
        if not any("USAGE" in privs for privs in sequence_grants):
            errs.append("manifest_writer must have USAGE on the run_outputs sequence")
        found = _role_has_forbidden(writer, WRITER_FORBIDDEN)
        if found:
            errs.append(f"manifest_writer must not have {', '.join(sorted(found))}")
        if not WRITER_FORBIDDEN.issubset(set(writer.get("forbidden", []))):
            errs.append("manifest_writer.forbidden must include UPDATE, DELETE, TRUNCATE")

    for role_name in ("manifest_reader", "ledger_auditor"):
        role = roles.get(role_name)
        if not isinstance(role, dict):
            errs.append(f"{role_name} must be an object")
            continue
        for table in REQUIRED_TABLES:
            if not _role_has_priv(role, table, "SELECT"):
                errs.append(f"{role_name} must have SELECT on {table}")
        found = _role_has_forbidden(role, READER_FORBIDDEN)
        if found:
            errs.append(f"{role_name} must not have {', '.join(sorted(found))}")
        if not READER_FORBIDDEN.issubset(set(role.get("forbidden", []))):
            errs.append(f"{role_name}.forbidden must include INSERT/UPDATE/DELETE/TRUNCATE")

    dba = roles.get("dba_admin")
    if not isinstance(dba, dict):
        errs.append("dba_admin must be an object")
    else:
        if _role_has_forbidden(dba, {"UPDATE", "DELETE"}):
            errs.append("dba_admin must not have routine UPDATE/DELETE grants")
        if "DISABLE_TRIGGER" not in set(dba.get("owner_operations", [])):
            errs.append("dba_admin.owner_operations must include DISABLE_TRIGGER")

    retention = policy.get("retention")
    if not isinstance(retention, dict):
        errs.append("retention must be an object")
    else:
        for key in (
            "legal_hold",
            "purge_requires_approval",
            "purge_requires_export",
            "purge_requires_dual_control",
        ):
            if retention.get(key) is not True:
                errs.append(f"retention.{key} must be true")
        minimum_days = retention.get("minimum_days")
        if status == "approved":
            if not isinstance(minimum_days, int) or minimum_days < 1:
                errs.append("approved policy requires retention.minimum_days >= 1")
        elif minimum_days is not None and (not isinstance(minimum_days, int) or minimum_days < 1):
            errs.append("retention.minimum_days must be null or a positive integer")

    incident = policy.get("incident_response")
    if not isinstance(incident, dict):
        errs.append("incident_response must be an object")
    else:
        for key in (
            "dual_control",
            "requires_incident_ticket",
            "requires_export_before_mutation",
            "post_incident_review",
            "re_enable_trigger_required",
            "evidence_retention_required",
        ):
            if incident.get(key) is not True:
                errs.append(f"incident_response.{key} must be true")
        break_glass = incident.get("break_glass_role")
        if break_glass not in roles:
            errs.append("incident_response.break_glass_role must reference a declared role")
        if break_glass in {"manifest_writer", "manifest_reader"}:
            errs.append("incident_response.break_glass_role must not be an app writer/reader")
        allowed = set(incident.get("break_glass_allowed_operations", []))
        if "DISABLE_TRIGGER" not in allowed:
            errs.append(
                "incident_response.break_glass_allowed_operations must include DISABLE_TRIGGER"
            )

    approvals = policy.get("approvals")
    if not isinstance(approvals, dict):
        errs.append("approvals must be an object")
    else:
        for key in REQUIRED_APPROVALS:
            if key not in approvals:
                errs.append(f"approvals missing {key}")
        if status == "approved":
            for key in REQUIRED_APPROVALS:
                value = approvals.get(key)
                if not isinstance(value, str) or not value.strip():
                    errs.append(f"approved policy requires approvals.{key} evidence")
    return errs


def is_approved(policy: dict) -> bool:
    return isinstance(policy, dict) and policy.get("status") == "approved"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"error: cannot read policy {args.policy}: {exc}", file=sys.stderr)
        return 2

    errs = check_policy(policy)
    approved = is_approved(policy)
    report = {
        "policy": str(args.policy),
        "schema": policy.get("schema") if isinstance(policy, dict) else None,
        "status": policy.get("status") if isinstance(policy, dict) else None,
        "approved": approved,
        "issues": errs,
        "result": "pass" if not errs else "fail",
    }
    if args.require_approved and not approved:
        report["issues"].append("--require-approved: policy is not approved")
        report["result"] = "fail"

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Policy: {args.policy}")
        print(f"Status: {report['status']} (approved={approved})")
        for issue in report["issues"]:
            print(f"FAIL: {issue}")
        if report["result"] == "pass":
            print("Result: PASS (structure/safety invariants only; not enforcement)")
        else:
            print(f"Result: FAIL ({len(report['issues'])} issue(s))")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
