#!/usr/bin/env python3

from pathlib import Path
import re
import sys

PLACEHOLDERS = {
    "TBD",
    "TODO",
    "Pending",
    "Example URL",
    "Example SHA",
    "Sample SHA",
    "Sample Workflow",
}

FILES = [
    "docs/evidence/m1.md",
    "docs/evidence/ci/m1-ci-evidence.md",
    "docs/evidence/attestations/m1-attestation.md",
    "docs/evidence/audit-checklist.md",
]

errors = []


def check_exists():
    for file in FILES:
        if not Path(file).exists():
            errors.append(f"Missing file: {file}")


def check_placeholders():
    for file in FILES:
        path = Path(file)

        if not path.exists():
            continue

        content = path.read_text(encoding="utf-8")

        for value in PLACEHOLDERS:
            if value in content:
                errors.append(f"{file} contains placeholder: {value}")


def check_status_consistency():
    path = Path("docs/evidence/m1.md")

    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")

    if re.search(r"Status:\s*CI PASS", text):
        ci_file = Path("docs/evidence/ci/m1-ci-evidence.md")

        if ci_file.exists():
            ci_text = ci_file.read_text(encoding="utf-8")

            if "GitHub Actions Run URL:\n\nTBD" in ci_text:
                errors.append(
                    "m1.md claims CI PASS but CI evidence incomplete"
                )


def main():
    check_exists()
    check_placeholders()
    check_status_consistency()

    if errors:
        print("VALIDATION FAILED")
        print()

        for error in errors:
            print(f"- {error}")

        sys.exit(1)

    print("VALIDATION PASSED")


if __name__ == "__main__":
    main()