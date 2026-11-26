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

STATUS_FILES = {
    "docs/evidence/m1.md",
    "docs/evidence/ci/m1-ci-evidence.md",
    "docs/evidence/attestations/m1-attestation.md",
}

REQUIRED_FILES = [
    "docs/evidence/README.md",
    "docs/evidence/m1.md",
    "docs/evidence/Prompt_M1approval.md",
    "docs/evidence/audit-checklist.md",
    "docs/evidence/ci/m1-ci-evidence.md",
    "docs/evidence/attestations/m1-attestation.md",
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


def get_status(text):
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


def contains_placeholders(text):
    found = []

    for placeholder in PLACEHOLDERS:
        if placeholder in text:
            found.append(placeholder)

    return found


def validate_required_files():
    for file in REQUIRED_FILES:
        if not Path(file).exists():
            errors.append(f"Missing required file: {file}")


def validate_placeholders(path, text):
    """
    Placeholder validation only applies
    to status-bearing evidence files.
    """

    if path not in STATUS_FILES:
        return

    status = get_status(text)

    #
    # Templates or files without status
    # are ignored.
    #
    if status is None:
        return

    #
    # BLOCKED state intentionally allows
    # TBD/TODO placeholders.
    #
    if status == "BLOCKED":
        return

    found = contains_placeholders(text)

    for item in found:
        errors.append(
            f"{path} contains placeholder '{item}' while status is {status}"
        )


def validate_github_actions_url(text):
    pattern = (
        r"https://github\.com/"
        r"[^\s]+/"
        r"actions/runs/"
        r"\d+"
    )

    return re.search(pattern, text) is not None


def validate_sha(text):
    return re.search(
        r"\b[a-f0-9]{40}\b",
        text,
        re.IGNORECASE,
    ) is not None


def validate_ci_evidence():
    text = read_file(CI_FILE)

    if not text:
        return

    validate_placeholders(CI_FILE, text)

    status = get_status(text)

    #
    # BLOCKED evidence may still
    # contain placeholders.
    #
    if status in (None, "BLOCKED"):
        return

    if not validate_github_actions_url(text):
        errors.append(
            "CI evidence is not BLOCKED but no valid GitHub Actions run URL was found"
        )

    if not validate_sha(text):
        errors.append(
            "CI evidence is not BLOCKED but no valid 40-character SHA was found"
        )


def validate_attestation():
    text = read_file(ATTESTATION_FILE)

    if not text:
        return

    validate_placeholders(ATTESTATION_FILE, text)

    m1_text = read_file(M1_FILE) or ""
    m1_status = get_status(m1_text)

    #
    # Attestation only enforced
    # once COMPLETE is claimed.
    #
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

    if not text:
        return

    validate_placeholders(M1_FILE, text)

    m1_status = get_status(text)

    if not m1_status:
        errors.append(
            "m1.md does not contain a valid status"
        )
        return

    ci_text = read_file(CI_FILE)

    if not ci_text:
        return

    ci_status = get_status(ci_text)

    #
    # COMPLETE requires CI evidence
    #
    if m1_status == "COMPLETE":

        if ci_status == "BLOCKED":
            errors.append(
                "m1.md reports COMPLETE but CI evidence remains BLOCKED"
            )

    #
    # CI PASS requires CI PASS evidence
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

    #
    # BLOCKED allows blocked evidence.
    #
    if m1_status == "BLOCKED":
        return

    if ci_status == "BLOCKED":
        errors.append(
            f"Status mismatch: m1.md={m1_status}, ci evidence={ci_status}"
        )


def validate():
    validate_required_files()

    for file in REQUIRED_FILES:
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