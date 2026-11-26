import subprocess
import sys
from pathlib import Path

import pytest


VALIDATOR = Path("scripts/validate_m1_evidence.py")


def run_validator():
    return subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
    )


def test_validator_exists():
    """Validator file exists."""
    assert VALIDATOR.exists()


def test_validator_compiles():
    """Validator has valid Python syntax."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(VALIDATOR),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )


@pytest.mark.smoke
def test_validator_executes():
    """
    End-to-end smoke test.

    Validator should:
    - execute successfully
    - return either 0 or 1
    - emit a recognizable validation result
    """

    result = run_validator()

    output = (
        result.stdout +
        result.stderr
    ).strip()

    assert result.returncode in (0, 1)

    assert (
        "VALIDATION PASSED" in output
        or
        "VALIDATION FAILED" in output
    ), output


@pytest.mark.smoke
def test_validator_emits_machine_readable_status():
    """Validator emits a stable status token."""

    result = run_validator()

    output = (
        result.stdout +
        result.stderr
    )

    expected_tokens = {
        "VALIDATION PASSED",
        "VALIDATION FAILED",
    }

    assert any(
        token in output
        for token in expected_tokens
    )


@pytest.mark.smoke
def test_validator_does_not_crash():
    """
    Protect against unexpected exceptions.
    """

    result = run_validator()

    output = (
        result.stdout +
        result.stderr
    )

    assert "Traceback" not in output