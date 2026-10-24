"""Deterministic runner for the file-based agent workflow.

The runner reads ``skills/<name>/SKILL.md``, validates its contract, and executes
only fixed entrypoints declared in this module. It never parses commands out of
Markdown, never uses a shell, and never reads ``.env`` values.

Usage:
    python -m scripts.agent_runner --list
    python -m scripts.agent_runner --skill data-validation --dry-run
    python -m scripts.agent_runner --skill data-validation
    python -m scripts.agent_runner --skill data-refresh-operations --yes
    python -m scripts.agent_runner --verify <run-id>

Write and heavy skills require ``--yes``. A skill with no entrypoint can still be
inspected with ``--dry-run``; its work is performed by following ``SKILL.md``.

The runner performs read-only preflight checks (git status, migrate --check when
DB-touching) and records them in ``preflight.json``. No environment values are
printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
ARTIFACTS_DIR = ROOT / "artifacts"

REQUIRED_SECTIONS = (
    "## When to use / when not to use",
    "## Runner",
    "## Preflight",
    "## Inputs",
    "## Procedure",
    "## Outputs",
    "## Verification",
    "## Failure handling",
    "## Handoffs",
    "## Stop conditions",
    "## Evidence required",
    "## Source of truth",
)
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MODULE = re.compile(r"^scripts\.[a-z][a-z0-9_]*$")
RISKS = ("read", "write", "heavy")
ENV_ROW = re.compile(r"^\|\s*Env\s*\|\s*`([A-Z][A-Z0-9_]*)`\s*\|\s*(yes[^|]*)\|", re.M)

#: Fixed argv tails, run as ``[sys.executable, "-m", *tail]``. A skill absent
#: from this mapping has no executable entrypoint.
ENTRYPOINTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "observability-nightly-verification": (("scripts.verify_nightly_run",),),
    "data-validation": (
        ("scripts.migrate", "--check"),
        ("scripts.check_schema_drift", "--quiet"),
    ),
    "data-storage-schema": (("scripts.migrate",),),
    "data-refresh-operations": (("scripts.run_full_etl",),),
}

#: Commands that prove a run. Run after the entrypoint and by ``--verify``
#: through the recorded ``verification.json``.
VERIFIERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "observability-nightly-verification": (("scripts.verify_nightly_run",),),
    "data-validation": (
        ("scripts.migrate", "--check"),
        ("scripts.check_schema_drift", "--quiet"),
    ),
    "data-storage-schema": (("scripts.migrate", "--check"),),
    "data-refresh-operations": (("scripts.verify_nightly_run",),),
}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    risk: str
    path: Path
    entrypoint_mode: str | None = None
    owner: str | None = None


class SkillError(ValueError):
    """The requested skill is missing or violates the SKILL.md contract."""


def _frontmatter(text: str, path: Path) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise SkillError(f"{path}: missing YAML frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise SkillError(f"{path}: malformed frontmatter line {line!r}")
        raw = value.strip()
        if raw[:1] in ("'", '"'):
            raw = raw.strip('"').strip("'")
        else:
            raw = raw.split(" #", 1)[0].strip()
        fields[key.strip()] = raw
    return fields


def load_skill(name: str, skills_dir: Path | None = None) -> Skill:
    """Load and validate one skill. Raise ``SkillError`` on any violation."""
    if not SKILL_NAME.match(name):
        raise SkillError(f"invalid skill name {name!r}; use kebab-case")
    path = (skills_dir or SKILLS_DIR) / name / "SKILL.md"
    if not path.is_file():
        raise SkillError(f"unknown skill {name!r}: {path} does not exist")

    text = path.read_text(encoding="utf-8")
    fields = _frontmatter(text, path)
    declared = fields.get("name")
    if declared != name:
        raise SkillError(f"{path}: frontmatter name {declared!r} does not match {name!r}")
    risk = fields.get("risk")
    if risk not in RISKS:
        raise SkillError(f"{path}: risk must be one of {RISKS}, got {risk!r}")
    description = fields.get("description", "")
    if len(description) < 30:
        raise SkillError(f"{path}: description is missing or too short")
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    if missing:
        raise SkillError(f"{path}: missing sections: {', '.join(missing)}")
    return Skill(
        name=name,
        description=description,
        risk=risk,
        path=path,
        entrypoint_mode=fields.get("entrypoint"),
        owner=fields.get("owner"),
    )


def list_skills(skills_dir: Path | None = None) -> list[Skill]:
    """Every valid skill directory, excluding the ``_template`` copy source."""
    directory = skills_dir or SKILLS_DIR
    skills = []
    for path in sorted(directory.glob("*/SKILL.md")):
        if path.parent.name.startswith("_"):
            continue
        skills.append(load_skill(path.parent.name, directory))
    return skills


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def _command_argv(tail: tuple[str, ...]) -> list[str]:
    module = tail[0]
    if not MODULE.match(module):
        raise SkillError(f"entrypoint {module!r} is not a scripts.* module")
    return [sys.executable, "-m", *tail]


def _run(argv: list[str], log, timeout: int) -> dict:
    log.write(f"$ {' '.join(argv)}\n")
    log.flush()
    try:
        result = subprocess.run(  # noqa: S603 - fixed modules, never a shell
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log.write(f"[timeout after {timeout}s]\n")
        return {
            "argv": argv,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "passed": False,
        }
    log.write(result.stdout)
    if result.stderr:
        log.write(result.stderr)
    log.write(f"[exit {result.returncode}]\n")
    log.flush()
    return {
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": result.returncode == 0,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _preflight(skill: Skill) -> dict:
    """Read-only preflight checks; no env values are printed."""
    checks = []
    try:
        result = subprocess.run(
            ["/usr/bin/git", "status", "--short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        checks.append(
            {
                "name": "git_status",
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "dirty": bool(result.stdout.strip()),
                "stdout": result.stdout,
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "git_status", "ok": False, "error": str(exc)})

    if skill.risk in ("write", "heavy") or skill.name in ENTRYPOINTS:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "scripts.migrate", "--check"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            checks.append(
                {
                    "name": "migrate_check",
                    "ok": result.returncode == 0,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "migrate_check", "ok": False, "error": str(exc)})

    for name, requirement in ENV_ROW.findall(skill.path.read_text(encoding="utf-8")):
        if requirement.strip().lower().startswith("yes"):
            checks.append(
                {
                    "name": f"env:{name}",
                    "ok": bool(os.environ.get(name)),
                    "present": bool(os.environ.get(name)),
                }
            )
    return {"skill": skill.name, "risk": skill.risk, "checks": checks}


def _plan(skill: Skill, entrypoint: tuple[tuple[str, ...], ...] | None) -> dict:
    return {
        "skill": skill.name,
        "description": skill.description,
        "risk": skill.risk,
        "entrypoint_mode": skill.entrypoint_mode,
        "owner": skill.owner,
        "skill_file": str(skill.path.relative_to(ROOT)),
        "entrypoints": [list(command) for command in entrypoint or ()],
        "verifiers": [list(command) for command in VERIFIERS.get(skill.name, ())],
    }


def _write_summary(path: Path, skill: Skill, results: list[dict], verified: bool) -> None:
    lines = [
        f"# Run: {skill.name}",
        "",
        f"- Risk: `{skill.risk}`",
        f"- Entrypoint mode: `{skill.entrypoint_mode or 'none'}`",
        f"- Owner: `{skill.owner or 'unassigned'}`",
        f"- Skill: `{skill.path.relative_to(ROOT)}`",
        f"- Commands: {len(results)}",
        "",
        "| Command | Exit | Result |",
        "|---|---|---|",
    ]
    for result in results:
        tail = " ".join(result["argv"][2:]) if len(result["argv"]) > 2 else ""
        code = result["returncode"] if result["returncode"] is not None else "timeout"
        lines.append(f"| `{tail}` | {code} | {'pass' if result['passed'] else 'fail'} |")
    lines += ["", f"Verification: {'passed' if verified else 'failed'}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_skill(
    name: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    run_id: str | None = None,
    timeout: int = 3600,
    skills_dir: Path | None = None,
    artifacts_dir: Path | None = None,
) -> int:
    """Validate one skill, then plan or execute its fixed entrypoint."""
    skill = load_skill(name, skills_dir)
    entrypoint = ENTRYPOINTS.get(name)
    verifiers = VERIFIERS.get(name)
    if entrypoint and not verifiers:
        raise SkillError(f"{name}: an entrypoint requires a verifier")

    identifier = run_id or _new_run_id()
    run_dir = (artifacts_dir or ARTIFACTS_DIR) / "runs" / identifier
    if run_dir.exists():
        raise SkillError(f"run id {identifier!r} already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    plan = _plan(skill, entrypoint)
    plan["run_id"] = identifier
    preflight = _preflight(skill)
    _write_json(run_dir / "plan.json", plan)
    _write_json(run_dir / "preflight.json", preflight)

    if dry_run:
        for command in entrypoint or ():
            print(f"python -m {' '.join(command)}")
        if not entrypoint:
            print(f"No executable entrypoint for {name}; follow {skill.path}.")
        print(f"plan: {run_dir / 'plan.json'}")
        print(f"preflight: {run_dir / 'preflight.json'}")
        return 0

    if not entrypoint:
        raise SkillError(f"{name}: no executable entrypoint; run with --dry-run to inspect")
    if skill.risk in ("write", "heavy") and not yes:
        print(f"{name} is {skill.risk}; re-run with --yes to execute", file=sys.stderr)
        return 2

    results = []
    with (run_dir / "commands.log").open("w", encoding="utf-8") as log:
        for command in entrypoint:
            result = _run(_command_argv(command), log, timeout)
            results.append(result)
            if not result["passed"]:
                break
        entrypoint_ok = all(result["passed"] for result in results) and len(results) == len(
            entrypoint
        )

        verify_results = []
        if entrypoint_ok:
            for command in verifiers or ():
                result = _run(_command_argv(command), log, timeout)
                verify_results.append(result)
                if not result["passed"]:
                    break

    verified = entrypoint_ok and all(result["passed"] for result in verify_results)
    _write_json(
        run_dir / "verification.json",
        {
            "run_id": identifier,
            "skill": name,
            "passed": verified,
            "entrypoint": results,
            "verifier": verify_results,
        },
    )
    _write_summary(run_dir / "summary.md", skill, results + verify_results, verified)
    print(f"run: {identifier}")
    print(f"verification: {'passed' if verified else 'failed'}")
    print(f"artifacts: {run_dir}")
    return 0 if verified else 1


def show_verification(run_id: str, artifacts_dir: Path | None = None) -> int:
    path = (artifacts_dir or ARTIFACTS_DIR) / "runs" / run_id / "verification.json"
    if not path.is_file():
        print(f"no verification record for run {run_id!r}: {path}", file=sys.stderr)
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"skill: {payload.get('skill')}")
    print(f"passed: {payload.get('passed')}")
    for category in ("entrypoint", "verifier"):
        for result in payload.get(category, []):
            tail = " ".join(result["argv"][2:])
            print(f"  {category}: python -m {tail} -> {result['returncode']}")
    return 0 if payload.get("passed") else 1


def main(argv: list[str] | None = None, artifacts_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List valid skills")
    group.add_argument("--skill", help="Skill directory name to run")
    group.add_argument("--verify", metavar="RUN_ID", help="Show a run's verification record")
    parser.add_argument("--dry-run", action="store_true", help="Write the plan, run nothing")
    parser.add_argument("--yes", action="store_true", help="Confirm a write or heavy skill")
    parser.add_argument("--run-id", help="Explicit run id (default: UTC timestamp + suffix)")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-command timeout in seconds")
    args = parser.parse_args(argv)

    try:
        if args.list:
            for skill in list_skills():
                print(f"{skill.name:<38} {skill.risk:<6} {skill.description}")
            return 0
        if args.verify:
            return show_verification(args.verify, artifacts_dir)
        return run_skill(
            args.skill,
            dry_run=args.dry_run,
            yes=args.yes,
            run_id=args.run_id,
            timeout=args.timeout,
            artifacts_dir=artifacts_dir,
        )
    except SkillError as exc:
        print(f"agent_runner: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
