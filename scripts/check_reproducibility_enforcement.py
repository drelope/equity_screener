"""Report RM-06 lock-enforcement gaps without claiming DEC-008 approval.

The checker is read-only. It inspects CI, Docker, and manifest source for locked
installs and hash policy. Exit 0 means the draft gap report was produced; gaps
are expected while DEC-008 is pending. Exit 1 means an artifact is missing or
unreadable, or ``--require-enforced`` was requested. Exit 2 is usage error.
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
    if "--require-hashes" not in text:
        gaps.append("CI does not enforce --require-hashes")
    if "pip install -r requirements.txt" in text:
        gaps.append("CI still installs unpinned requirements.txt")
    if "check_reproducibility_locks.py" not in text:
        gaps.append("CI does not run the lock-file scaffolding check")
    return gaps


def check_docker(text: str) -> list[str]:
    gaps: list[str] = []
    if "requirements.lock.txt" not in text:
        gaps.append("Dockerfile does not install from requirements.lock.txt")
    if "--require-hashes" not in text:
        gaps.append("Dockerfile does not enforce --require-hashes")
    if "-r requirements.txt" in text:
        gaps.append("Dockerfile still installs unpinned requirements.txt")
    if "--ignore-installed pillow" in text:
        gaps.append("Dockerfile has an unpinned pillow override")
    return gaps


def check_manifest_capture(text: str) -> list[str]:
    gaps: list[str] = []
    if "get_dependency_lock_hashes" not in text:
        gaps.append("run manifests do not capture dependency lock hashes")
    return gaps


def check_policy(text: str) -> list[str]:
    normalized = text.replace("**", "").replace("`", "")
    gaps: list[str] = []
    if "Draft/scaffolding only" not in normalized or "DEC-008 pending" not in normalized:
        gaps.append("reproducibility policy lost its DEC-008 draft status")
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

    if require_enforced:
        report["errors"].append("locked-install enforcement is not approved; DEC-008 is pending")
        report["status"] = "fail_enforcement_not_approved"
    elif report["errors"]:
        report["status"] = "fail"
    else:
        report["status"] = "pass_draft_gap_report"
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
        print("enforcement_claim=false; this report cannot claim DEC-008 enforcement")
    return 0 if report["status"] == "pass_draft_gap_report" else 1


if __name__ == "__main__":
    raise SystemExit(main())
