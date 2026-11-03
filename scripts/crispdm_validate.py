#!/usr/bin/env python
"""Quick validation script for CRISP-DM workflow gates."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd, desc):
    print(f"\n=== {desc} ===")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)  # noqa: S603
    print(f"Exit: {result.returncode}")
    return result.returncode == 0


def main():
    checks = []
    checks.append(
        run_cmd([sys.executable, "-m", "scripts.migrate", "--check"], "Schema migration check")
    )
    checks.append(run_cmd(["ruff", "check", "."], "Lint check"))
    checks.append(run_cmd(["ruff", "format", "--check", "."], "Format check"))
    checks.append(run_cmd([sys.executable, "-m", "scripts.skill_audit", "--all"], "Skill audit"))
    checks.append(run_cmd([sys.executable, "-m", "pytest", "-q"], "Tests"))

    print("\n=== Summary ===")
    print(f"Passed: {sum(checks)}/{len(checks)}")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
