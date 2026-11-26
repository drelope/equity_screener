#!/usr/bin/env python3

from pathlib import Path
import re
import sys

PLACEHOLDERS = {
    "TBD",
    "TODO",
    "Pending",
    "Not yet recorded",
    "Example URL",
    "Example SHA",
    "Sample SHA",
    "Sample Workflow",
    "<run-url>",
    "<sha>",
    "<workflow>",
}

FILES = [
    "docs/evidence/m1.md",
    "docs/evidence/ci/m1-ci-evidence.md",
    "docs/evidence/attestations/m1-attestation.md",
    "docs/evidence/audit-checklist.md",
]

M1_FILE = "docs/evidence/m1.md"
CI_FILE = "docs/evidence/ci/m1-ci-evidence.md"
ATTESTATION_FILE = "docs/evidence/attestations/m1-attestation.md"

VALID_STATUSES = {
    "BLOCKED",
    "CI PASS",
    "COMPLETE",
}

errors = []


def read_file(path):
    p = Path(path)

    if not p.exists():
        return None

    return p.read_text(encoding="utf-8")


def check_required_files():
    for file in FILES:
        if not Path(file).exists():
            errors.append(f"Missing required file: {file}")


def get_status(text):
    """
    Finds:
        Status: BLOCKED
        Status: CI PASS
        Status: COMPLETE
    """

    if not text:
        return None

    match = re.search(
        r"Status:\s*(BLOCKED|CI PASS|COMPLETE)",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1).upper()


def contains_placeholder(text):
    found = []

    for value in PLACEHOLDERS:
        if value in text:
            found.append(value)

    return found


def validate_placeholders(path, text):
    status = get_status(text)

    if status == "BLOCKED":
        return

    found = contains_placeholder(text)

    for item in found:
        errors.append(
            f"{path} contains placeholder '{item}' while status is {status}"
        )


def validate_github_actions_url(ci_text):
    match = re.search(
        r"https://github\.com/[^\s]+/actions/runs/\d+",
        ci_text
    )

    return match is not None


def validate_sha(ci_text):
    match = re.search(
        r"\b[a-f0-9]{40}\b",
        ci_text,
        re.IGNORECASE,
    )

    return match is not None


def validate_ci_evidence():
    text = read_file(CI_FILE)

    if text is None:
        return

    status = get_status(text)

    validate_placeholders(CI_FILE, text)

    if status == "BLOCKED":
        return

    if not validate_github_actions_url(text):
        errors.append(
            "CI evidence status is not BLOCKED but no valid GitHub Actions run URL was found"
        )

    if not validate_sha(text):
        errors.append(
            "CI evidence status is not BLOCKED but no valid 40-character SHA was found"
        )


def validate_attestation():
    text = read_file(ATTESTATION_FILE)

    if text is None:
        return

    validate_placeholders(ATTESTATION_FILE, text)

    m1_status = get_status(read_file(M1_FILE) or "")

    if m1_status != "COMPLETE":
        return

    required_fields = [
        "Maintainer:",
        "Tested SHA:",
        "GitHub Actions Run:",
        "Workflow:",
    ]

    for field in required_fields:
        if field not in text:
            errors.append(
                f"Attestation missing required field: {field}"
            )


def validate_m1_status():
    text = read_file(M1_FILE)

    if text is None:
        return

    validate_placeholders(M1_FILE, text)

    m1_status = get_status(text)

    if m1_status not in VALID_STATUSES:
        errors.append(
            "m1.md does not contain a valid status"
        )
        return

    ci_text = read_file(CI_FILE)

    if ci_text is None:
        return

    ci_status = get_status(ci_text)

    #
    # COMPLETE requires CI PASS evidence
    #
    if m1_status == "COMPLETE":

        if ci_status == "BLOCKED":
            errors.append(
                "m1.md is COMPLETE but CI evidence remains BLOCKED"
            )

    #
    # CI PASS requires CI evidence
    #
    if m1_status == "CI PASS":

        if ci_status == "BLOCKED":
            errors.append(
                "m1.md reports CI PASS but CI evidence remains BLOCKED"
            )


def validate_cross_file_consistency():
    m1_text = read_file(M1_FILE)
    ci_text = read_file(CI_FILE)

    if not m1_text or not ci_text:
        return

    m1_status = get_status(m1_text)
    ci_status = get_status(ci_text)

    if m1_status == "BLOCKED":
        return

    if ci_status == "BLOCKED":
        errors.append(
            f"Status mismatch: m1.md={m1_status}, ci evidence={ci_status}"
        )


def validate():
    check_required_files()

    for file in FILES:
        text = read_file(file)

        if text:
            validate_placeholders(file, text)

    validate_ci_evidence()
    validate_attestation()
    validate_m1_status()
    validate_cross_file_consistency()


def main():
    validate()

    if errors:
        print("VALIDATION FAILED")
        print()

        for error in errors:
            print(f"- {error}")

        sys.exit(1)

    print("VALIDATION PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()