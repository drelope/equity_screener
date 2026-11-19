"""Validate the draft P0 evidence bundle without asserting promotion readiness.

Exit 0 means the declared evidence files exist, match their hashes, and the
bundle still carries explicit non-promotion status. Exit 1 means the bundle is
incomplete or inconsistent. Exit 2 means usage/IO error. The
``--require-promotion-grade`` option always fails by design: human approvals and
external acceptance evidence are required before promotion can be claimed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = (
    PROJECT_ROOT
    / "docs"
    / "speckit-recovery"
    / "08-implementation-validation"
    / "evidence-closeout-index.json"
)

REQUIRED_SCHEMA = "p0_evidence_closeout/v1"
REQUIRED_STATUS = "draft_not_promotion_grade"
ALLOWED_KINDS = {
    "status_snapshot",
    "execution_log",
    "rtm",
    "readme",
    "policy_draft",
    "candidate_manifest",
    "candidate_rehearsal",
    "backfill_readiness",
    "synthetic_rehearsal",
    "governance_policy",
    "promotion_policy",
    "reproducibility_policy",
    "migration_plan",
    "code_scaffolding",
    "code_scaffolding",
    "ci_gate",
}
ALLOWED_CLAIM_SCOPES = {
    "workspace_status",
    "execution_record",
    "static_consistency",
    "isolated_rehearsal",
    "read_only_diagnostics",
    "synthetic_rehearsal",
    "draft_policy",
    "local_test_result",
    "draft_scaffolding",
    "ci_gate",
}
REQUIRED_KINDS = {
    "status_snapshot",
    "execution_log",
    "rtm",
    "candidate_manifest",
    "candidate_rehearsal",
    "backfill_readiness",
    "synthetic_rehearsal",
    "governance_policy",
    "promotion_policy",
    "reproducibility_policy",
    "ci_gate",
}
REQUIRED_ARTIFACT_FIELDS = ("id", "path", "sha256", "kind", "purpose", "claim_scope")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_index(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def check_index(index: dict[str, Any], root: Path) -> list[str]:
    errs: list[str] = []
    if not isinstance(index, dict):
        return ["index must be a JSON object"]
    if index.get("schema") != REQUIRED_SCHEMA:
        errs.append(f"schema must be {REQUIRED_SCHEMA!r}")
    if index.get("status") != REQUIRED_STATUS:
        errs.append(f"status must be {REQUIRED_STATUS!r}")
    if index.get("promotion_claim") is not False:
        errs.append("promotion_claim must be false")
    blockers = index.get("promotion_blockers")
    if (
        not isinstance(blockers, list)
        or not blockers
        or not all(isinstance(x, str) and x.strip() for x in blockers)
    ):
        errs.append("promotion_blockers must be a non-empty list of strings")

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errs + ["artifacts must be a non-empty list"]

    seen: set[str] = set()
    kinds: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            errs.append("artifact entry must be an object")
            continue
        missing = [field for field in REQUIRED_ARTIFACT_FIELDS if field not in item]
        artifact_id = str(item.get("id", "?"))
        if missing:
            errs.append(f"{artifact_id}: missing {', '.join(missing)}")
            continue
        if artifact_id in seen:
            errs.append(f"duplicate artifact id: {artifact_id}")
        seen.add(artifact_id)
        if item.get("promotion_claim") is True:
            errs.append(f"{artifact_id}: artifact claims promotion")
        if item.get("kind") not in ALLOWED_KINDS:
            errs.append(f"{artifact_id}: unsupported kind {item.get('kind')!r}")
        else:
            kinds.add(item["kind"])
        if item.get("claim_scope") not in ALLOWED_CLAIM_SCOPES:
            errs.append(f"{artifact_id}: unsupported claim_scope {item.get('claim_scope')!r}")
        path = _relative_path(root, item.get("path"))
        if path is None:
            errs.append(f"{artifact_id}: path must be a relative path inside the repository")
            continue
        if not path.is_file():
            errs.append(f"{artifact_id}: missing file {item['path']}")
            continue
        if item.get("sha256") != sha256_file(path):
            errs.append(f"{artifact_id}: sha256 mismatch for {item['path']}")

    missing_kinds = sorted(REQUIRED_KINDS - kinds)
    if missing_kinds:
        errs.append(f"missing required evidence kinds: {', '.join(missing_kinds)}")
    return errs


def check_live_draft_state(root: Path) -> list[str]:
    errs: list[str] = []
    checks = [
        (
            root
            / "docs/speckit-recovery/08-implementation-validation/promotion-policy-template.json",
            "status",
            "approved",
            "promotion policy must not be approved in this draft gate",
            True,
        ),
        (
            root
            / "docs/speckit-recovery/08-implementation-validation/sql-candidates/candidate-manifest.json",
            "status",
            "candidate_not_applied",
            "candidate manifest must remain candidate_not_applied",
            False,
        ),
        (
            root
            / "docs/speckit-recovery/08-implementation-validation/manifest-ledger-governance-policy-template.json",
            "status",
            "draft_not_approved",
            "ledger governance policy must remain draft_not_approved",
            False,
        ),
    ]
    for path, field, forbidden, message, must_not_equal in checks:
        try:
            data = load_index(path)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"unreadable {path.name}: {exc}")
            continue
        value = data.get(field)
        if (must_not_equal and value == forbidden) or (not must_not_equal and value != forbidden):
            errs.append(message)

    contract = (
        root / "docs/speckit-recovery/08-implementation-validation/promotion-gate-contract-draft.md"
    )
    if "No promotion-grade gate is implemented or passed by this draft" not in contract.read_text(
        encoding="utf-8"
    ):
        errs.append("promotion gate contract lost its explicit non-promotion statement")
    reproducibility = (
        root
        / "docs/speckit-recovery/08-implementation-validation/reproducibility-lock-policy-draft.md"
    )
    text = reproducibility.read_text(encoding="utf-8").replace("**", "").replace("`", "")
    if "Ratified 2026-11-18" not in text:
        errs.append("reproducibility policy lost its DEC-008 ratification record")
    if "exact pins plus lock-file SHA-256" not in text:
        errs.append("reproducibility policy lost the ratified lock strategy")
    return errs


def run(index_path: Path, root: Path, require_promotion_grade: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "index": str(index_path),
        "root": str(root),
        "status": "failed",
        "promotion_claim": False,
        "promotion_grade": False,
        "issues": [],
    }
    if require_promotion_grade:
        report["issues"].append(
            "promotion-grade closeout is not implemented; approvals and external acceptance evidence are required"
        )
        return report
    try:
        index = load_index(index_path)
    except Exception as exc:  # noqa: BLE001
        report["issues"].append(f"unreadable index: {exc}")
        return report
    issues = check_index(index, root) + check_live_draft_state(root)
    report["issues"] = issues
    report["artifact_count"] = len(index.get("artifacts", [])) if isinstance(index, dict) else 0
    report["status"] = "pass_draft_not_promotion_grade" if not issues else "fail"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--require-promotion-grade", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(args.index, args.root, args.require_promotion_grade)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"status={report['status']} artifacts={report.get('artifact_count', 0)}")
        for issue in report["issues"]:
            print(f"FAIL: {issue}")
        print("promotion_grade=false; this gate cannot claim promotion readiness")
    return 0 if report["status"] == "pass_draft_not_promotion_grade" else 1


if __name__ == "__main__":
    raise SystemExit(main())
