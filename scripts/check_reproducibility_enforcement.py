"""Report RM-06 lock-enforcement status without claiming clean-environment parity.

The checker is read-only. It inspects CI, Docker, manifest source, and the proposed
DEC-008 policy. Exit 0 means local enforcement checks pass; exit 1 means an
artifact is missing/unreadable, a gap remains, or ``--require-enforced`` is
requested before parity evidence exists. Exit 2 is usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_reproducibility_locks import parse_lock  # noqa: E402

CI_PATH = Path(".github/workflows/ci.yml")
DOCKER_PATH = Path("Dockerfile")
COMPOSE_PATH = Path("docker-compose.yml")
MANIFEST_PATH = Path("src/crispdm/run_manifest.py")
POLICY_PATH = Path(
    "docs/speckit-recovery/08-implementation-validation/reproducibility-lock-policy-draft.md"
)
LOCK_FILES = (Path("requirements.lock.txt"), Path("requirements-dev.lock.txt"))


def read_text(root: Path, relative: Path) -> tuple[str | None, str | None]:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as exc:  # noqa: BLE001
        return None, f"unreadable {relative}: {exc}"


def check_lock_files(root: Path) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    counts: dict[str, int] = {}
    for relative in LOCK_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(f"missing lock file: {relative}")
            continue
        pins, invalid = parse_lock(path)
        counts[str(relative)] = len(pins)
        if not pins:
            errors.append(f"no pinned entries in {relative}")
        errors.extend(f"{relative}: {line}" for line in invalid)
    return errors, counts


def check_ci(text: str) -> list[str]:
    gaps: list[str] = []
    if "requirements.lock.txt" not in text:
        gaps.append("CI does not install from requirements.lock.txt")
    if "check_reproducibility_locks.py" not in text:
        gaps.append("CI does not run the lock-file scaffolding check")
    if "pip install -r requirements.txt" in text:
        gaps.append("CI still installs unpinned requirements.txt")
    return gaps


def check_docker(text: str) -> list[str]:
    gaps: list[str] = []
    if "requirements.lock.txt" not in text:
        gaps.append("Dockerfile does not install from requirements.lock.txt")
    if "-r requirements.txt" in text:
        gaps.append("Dockerfile still installs unpinned requirements.txt")
    if "--ignore-installed pillow" in text:
        gaps.append("Dockerfile has an unpinned pillow override")
    return gaps


def check_manifest_capture(text: str) -> list[str]:
    gaps: list[str] = []
    if "get_dependency_lock_hashes" not in text:
        gaps.append("run manifests do not capture dependency lock hashes")
    if "lock_strategy_version" not in text:
        gaps.append("run manifests do not capture lock strategy version")
    if "platform_python" not in text or "platform_system" not in text:
        gaps.append("run manifests do not capture platform identity")
    return gaps


def check_policy(text: str) -> list[str]:
    normalized = text.replace("**", "").replace("`", "")
    gaps: list[str] = []
    if "approval pending" not in normalized:
        gaps.append("reproducibility policy does not mark DEC-008 approval as pending")
    if "exact pins plus lock-file SHA-256" not in normalized:
        gaps.append("reproducibility policy does not record the proposed lock strategy")
    return gaps


def run(root: Path, require_enforced: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "root": str(root),
        "enforcement_claim": False,
        "promotion_claim": False,
        "gaps": [],
        "errors": [],
        "lock_counts": {},
        "status": "failed",
    }
    lock_errors, counts = check_lock_files(root)
    report["errors"].extend(lock_errors)
    report["lock_counts"] = counts

    for relative, checker in (
        (CI_PATH, check_ci),
        (DOCKER_PATH, check_docker),
        (MANIFEST_PATH, check_manifest_capture),
        (POLICY_PATH, check_policy),
    ):
        text, error = read_text(root, relative)
        if error:
            report["errors"].append(error)
            continue
        if checker is check_ci:
            report["gaps"].extend(f"CI: {gap}" for gap in checker(text or ""))
        elif checker is check_docker:
            report["gaps"].extend(f"Docker: {gap}" for gap in checker(text or ""))
        elif checker is check_manifest_capture:
            report["gaps"].extend(f"Manifest: {gap}" for gap in checker(text or ""))
        else:
            report["gaps"].extend(f"Policy: {gap}" for gap in checker(text or ""))

    compose_text, compose_error = read_text(root, COMPOSE_PATH)
    if compose_error:
        report["errors"].append(compose_error)
    elif "postgres:17.11@sha256:" in (compose_text or ""):
        report["digest_pinned_postgres"] = True
    else:
        report["gaps"].append("Compose: postgres image is not digest-pinned")

    if report["errors"]:
        report["status"] = "fail"
    elif report["gaps"]:
        report["status"] = "fail_gaps"
    elif require_enforced:
        report["errors"].append("clean-environment parity evidence is not yet recorded")
        report["status"] = "fail_parity_not_verified"
    else:
        report["status"] = "pass_local_enforcement"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--require-enforced", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(args.root, args.require_enforced)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"status={report['status']} gaps={len(report['gaps'])} errors={len(report['errors'])}"
        )
        for gap in report["gaps"]:
            print(f"GAP: {gap}")
        for error in report["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        print("enforcement_claim=false; local enforcement is not AC-P0-09 closure")
    return 0 if report["status"] == "pass_local_enforcement" else 1


if __name__ == "__main__":
    raise SystemExit(main())
