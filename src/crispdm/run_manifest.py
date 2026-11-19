"""Run manifest helpers for immutable, evidence-oriented execution records.

This module provides lightweight, deterministic manifest construction and hashing
utilities (RM-04 foundation). It does not persist manifests or integrate pipelines;
callers are responsible for storage, immutability enforcement, and run lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


LOCK_STRATEGY = "exact_pins_plus_lock_sha256"
LOCK_STRATEGY_VERSION = "1.0.0"


def get_dependency_lock_hashes(root: str | Path | None = None) -> dict[str, str | None]:
    """Return ratified dependency identity for known lock artifacts.

    Missing files are reported as ``None`` so manifests can record partial state.
    With ``root`` provided, only that path is searched; otherwise cwd and the
    repository root are searched. The strategy is exact pins plus the SHA-256 of
    each lock file, matching DEC-008; per-package hashes are not used.
    """
    if root is not None:
        candidates = [Path(root)]
    else:
        candidates = [Path.cwd(), Path(__file__).resolve().parents[2]]
    hashes: dict[str, str | None] = {
        "requirements.lock.txt": None,
        "requirements-dev.lock.txt": None,
    }
    for base in candidates:
        for name in list(hashes):
            if hashes[name] is not None:
                continue
            path = base / name
            if path.exists():
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    hashes["lock_strategy"] = LOCK_STRATEGY
    hashes["lock_strategy_version"] = LOCK_STRATEGY_VERSION
    hashes["platform_python"] = platform.python_version()
    hashes["platform_system"] = platform.system()
    hashes["platform_machine"] = platform.machine()
    return hashes


def get_git_state(cwd: str | Path | None = None) -> dict[str, Any]:
    """Best-effort git SHA/dirty state for provenance; returns nulls on failure."""
    git = shutil.which("git")
    if not git:
        return {"sha": None, "dirty": None}
    try:
        sha = subprocess.check_output(  # noqa: S603
            [git, "rev-parse", "HEAD"], cwd=cwd, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = (
            subprocess.call(  # noqa: S603
                [git, "diff", "--quiet", "--ignore-submodules", "HEAD", "--"],
                cwd=cwd,
                stderr=subprocess.DEVNULL,
            )
            != 0
        )
        return {"sha": sha or None, "dirty": dirty}
    except Exception:
        return {"sha": None, "dirty": None}


def canonical_json(value: Any) -> str:
    """Deterministic JSON serialization for hashing/comparison."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON representation."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_run_manifest(
    *,
    run_type: str,
    code_sha: str | None = None,
    code_dirty: bool | None = None,
    config: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    inputs: Mapping[str, Any] | Sequence[Any] | None = None,
    outputs: Mapping[str, Any] | Sequence[Any] | None = None,
    resolved_as_of: str | None = None,
    acceptance_policy_id: str | None = None,
    acceptance_policy_version: str | None = None,
    environment: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    created_at_utc: str | None = None,
    status: str = "created",
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a manifest payload with stable hashes for core execution inputs.

    Required for material runs in target architecture: run identity, code/config/
    parameter/input provenance, as-of context, and output refs. This helper
    computes hashes from provided structures; callers must supply authoritative
    values (e.g. real git SHA, lock hashes, snapshot IDs).
    """
    if not run_type or not str(run_type).strip():
        raise ValueError("run_type is required")

    config_obj = dict(config or {})
    parameters_obj = dict(parameters or {})
    inputs_obj = inputs if inputs is not None else {}
    outputs_obj = outputs if outputs is not None else {}
    environment_obj = dict(environment or {})
    if "dependency_lock_hashes" not in environment_obj:
        environment_obj["dependency_lock_hashes"] = get_dependency_lock_hashes()

    manifest = {
        "run_id": run_id or str(uuid4()),
        "run_type": str(run_type),
        "status": status,
        "created_at_utc": created_at_utc or _utc_now_iso(),
        "code": {
            "sha": code_sha,
            "dirty": code_dirty,
        },
        "resolved_as_of": resolved_as_of,
        "acceptance_policy": {
            "id": acceptance_policy_id,
            "version": acceptance_policy_version,
            "hash": sha256_hex(
                {
                    "id": acceptance_policy_id,
                    "version": acceptance_policy_version,
                }
            )
            if acceptance_policy_id or acceptance_policy_version
            else None,
        },
        "config": config_obj,
        "parameters": parameters_obj,
        "inputs": inputs_obj,
        "outputs": outputs_obj,
        "environment": environment_obj,
        "hashes": {
            "config_hash": sha256_hex(config_obj),
            "parameters_hash": sha256_hex(parameters_obj),
            "inputs_hash": sha256_hex(inputs_obj),
            "environment_hash": sha256_hex(environment_obj),
            "manifest_core_hash": None,
        },
        "notes": notes,
    }
    manifest["hashes"]["manifest_core_hash"] = sha256_hex(
        {
            "run_type": manifest["run_type"],
            "code": manifest["code"],
            "resolved_as_of": manifest["resolved_as_of"],
            "acceptance_policy": manifest["acceptance_policy"],
            "hashes": {
                "config_hash": manifest["hashes"]["config_hash"],
                "parameters_hash": manifest["hashes"]["parameters_hash"],
                "inputs_hash": manifest["hashes"]["inputs_hash"],
                "environment_hash": manifest["hashes"]["environment_hash"],
            },
        }
    )
    return manifest


def write_manifest_file(
    manifest: Mapping[str, Any],
    path: str | Path,
    *,
    append_registry: bool = True,
    registry_path: str | Path | None = None,
) -> Path:
    """Write manifest JSON deterministically and optionally append to JSONL registry.

    Individual manifest files are immutable-by-convention per unique path; the
    optional JSONL registry provides an append-only evidence index (RM-04 draft).
    Registry append failures are not raised to avoid breaking material runs.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(manifest) + "\n"
    out.write_text(payload, encoding="utf-8")

    if append_registry:
        reg = (
            Path(registry_path)
            if registry_path is not None
            else out.parent.parent / "manifest_registry.jsonl"
        )
        try:
            reg.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "recorded_at_utc": _utc_now_iso(),
                "manifest_path": str(out),
                "run_id": manifest.get("run_id"),
                "run_type": manifest.get("run_type"),
                "manifest_hash": sha256_hex(manifest),
            }
            with reg.open("a", encoding="utf-8") as f:
                f.write(canonical_json(record) + "\n")
        except Exception:  # noqa: BLE001, S110 - best-effort append-only index
            pass
    return out
