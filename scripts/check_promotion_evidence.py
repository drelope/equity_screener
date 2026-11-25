"""RM-07 scaffolding: check presence/linkage of promotion/evaluation evidence fields.

Draft only (DEC-002..005 pending). This validates artifact structure/presence,
not correctness, statistical validity, or approval. Exit 0 means required draft
fields were found; exit 1 means missing/incomplete evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_CHECKPOINT_PATHS = [
    ("run_id",),
    ("contract", "acceptance_policy_version"),
    ("contract", "model_version"),
    ("contract", "feature_version"),
    ("contract", "data_version"),
    ("gate", "passed"),
    ("gate", "checks"),
    ("readiness",),
]

REQUIRED_BACKTEST_METRICS = [
    "periods",
    "held_periods",
    "cash_periods",
]

PROMOTION_GRADE_REQUIRED = [
    "holdout",
    "cost_model",
    "exposure_matched_benchmark",
    "acceptance_policy_ref",
    "manifest_ref",
]

DRAFT_CONTRACT_PATHS = [
    ("cost_model", "id"),
    ("cost_model", "version"),
    ("cost_model", "status"),
    ("benchmark", "id"),
    ("benchmark", "version"),
    ("benchmark", "status"),
    ("holdout", "contract_id"),
    ("holdout", "contract_version"),
    ("holdout", "status"),
    ("acceptance_policy", "id"),
    ("acceptance_policy", "version"),
    ("acceptance_policy", "change_control_ref"),
    ("promotion_decision", "acceptance_policy_ref"),
]


DEFAULT_POLICY = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "speckit-recovery"
    / "08-implementation-validation"
    / "promotion-policy-template.json"
)

# Policy fields that must be concrete before any promotion-grade claim.
POLICY_REQUIRED_PATHS = [
    ("holdout", "id"),
    ("holdout", "freeze_date"),
    ("holdout", "owner"),
    ("holdout", "untouched_evidence_ref"),
    ("acceptance_policy", "change_control_ref"),
    ("cost_model", "id"),
    ("cost_model", "version"),
    ("cost_model", "assumptions", "commission_bps"),
    ("cost_model", "assumptions", "spread_bps"),
    ("cost_model", "assumptions", "slippage_bps"),
    ("cost_model", "assumptions", "cash_treatment"),
    ("benchmark", "id"),
    ("benchmark", "version"),
    ("benchmark", "universe_alignment"),
    ("benchmark", "exposure_alignment"),
    ("benchmark", "rebalance_alignment"),
    ("benchmark", "cash_treatment"),
    ("promotion_decision", "approver"),
    ("promotion_decision", "approved_at"),
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_draft_contract(policy_path: Path) -> list[str]:
    """Return missing draft-contract fields; presence is not promotion evidence."""
    if not policy_path.exists():
        return [f"missing promotion policy: {policy_path}"]
    try:
        policy = load_json(policy_path)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable promotion policy {policy_path}: {exc}"]
    errs: list[str] = []
    for path in DRAFT_CONTRACT_PATHS:
        value = get_path(policy, path)
        if value is None or value == "":
            errs.append(f"draft contract gap: {'.'.join(path)} is not set")
    if policy.get("status") == "approved":
        errs.append("draft contract must remain unapproved while decision evidence is pending")
    return errs


def check_policy_gaps(policy_path: Path) -> list[str]:
    """Return one gap per null/empty policy field; policy itself must be readable."""
    if not policy_path.exists():
        return [f"missing promotion policy: {policy_path}"]
    try:
        policy = load_json(policy_path)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable promotion policy {policy_path}: {exc}"]
    gaps = []
    for path in POLICY_REQUIRED_PATHS:
        value = get_path(policy, path)
        if value is None or value == "":
            gaps.append(f"policy gap: {'.'.join(path)} is not set")
    if not policy.get("holdout", {}).get("snapshot_refs"):
        gaps.append("policy gap: holdout.snapshot_refs is empty")
    if not policy.get("promotion_decision", {}).get("evidence_refs"):
        gaps.append("policy gap: promotion_decision.evidence_refs is empty")
    if policy.get("status") != "approved":
        gaps.append(f"policy gap: status is {policy.get('status')!r}, not 'approved'")
    return gaps


def get_path(obj, path):
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def check_checkpoint(path: Path) -> list[str]:
    errs: list[str] = []
    if not path.exists():
        return [f"missing checkpoint: {path}"]
    try:
        data = load_json(path)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable checkpoint {path}: {exc}"]
    for p in REQUIRED_CHECKPOINT_PATHS:
        if get_path(data, p) is None:
            errs.append(f"checkpoint missing field: {'.'.join(p)}")
    # promotion-grade evidence explicitly not assumed present
    for key in ("holdout", "cost_model", "benchmark"):
        if key not in data:
            errs.append(f"promotion-grade field absent (expected draft gap): {key}")
    return errs


def check_backtest_metrics(path: Path) -> list[str]:
    errs: list[str] = []
    if not path.exists():
        return [f"missing backtest metrics: {path}"]
    try:
        data = load_json(path)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable backtest metrics {path}: {exc}"]
    for key in REQUIRED_BACKTEST_METRICS:
        if key not in data:
            errs.append(f"backtest metrics missing field: {key}")
    cm = data.get("cost_model")
    if not isinstance(cm, dict) or cm.get("applied") is not True:
        errs.append("promotion-grade gap: cost_model not applied/approved (draft or missing)")
    emb = data.get("exposure_matched_benchmark")
    if not isinstance(emb, dict) or emb.get("applied") is not True:
        errs.append(
            "promotion-grade gap: exposure_matched_benchmark not applied/approved (draft or missing)"
        )
    if data.get("net_metrics_status") in (None, "not_computed_draft") and "net_return" not in data:
        errs.append("promotion-grade gap: net metrics not computed (draft)")
    return errs


def check_manifest(path: Path) -> list[str]:
    errs: list[str] = []
    if not path.exists():
        return [f"missing manifest: {path}"]
    try:
        data = load_json(path)
    except Exception as exc:  # noqa: BLE001
        return [f"unreadable manifest {path}: {exc}"]
    for key in ("run_id", "run_type", "created_at_utc", "code", "hashes"):
        if key not in data:
            errs.append(f"manifest missing field: {key}")
    return errs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--backtest-metrics", type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    p.add_argument("--require-promotion-grade", action="store_true")
    args = p.parse_args(argv)

    errs: list[str] = []
    checked = 0
    if args.checkpoint:
        errs.extend(check_checkpoint(args.checkpoint))
        checked += 1
    if args.backtest_metrics:
        errs.extend(check_backtest_metrics(args.backtest_metrics))
        checked += 1
    if args.manifest:
        errs.extend(check_manifest(args.manifest))
        checked += 1
    if checked == 0:
        print("No artifacts specified; nothing checked.", file=sys.stderr)
        return 2

    errs.extend(check_draft_contract(args.policy))

    if args.require_promotion_grade:
        gaps = check_policy_gaps(args.policy)
        errs.extend(gaps)
        if not gaps:
            errs.append(
                "promotion-grade artifact content is not verified by this draft checker "
                "(holdout freeze, cost/benchmark economics, and statistics remain external)"
            )

    if errs:
        for e in errs:
            print(f"FAIL: {e}")
        print(f"Result: FAIL ({len(errs)} issue(s))")
        return 1
    print("Result: PASS (draft structure checks only; not promotion-grade evidence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
