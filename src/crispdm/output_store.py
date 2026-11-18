"""Run-keyed, non-overwriting output store (RM-05 draft scaffolding).

Outputs are written under a caller-supplied root as
``<run_id>/<output_kind>.json``. A rerun with the same payload is idempotent;
a different payload for the same run/output pair raises instead of overwriting.
This is file-based scaffolding only: it does not wire the app or pipelines, and
it does not claim the persisted/run-keyed acceptance criteria are met.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .run_manifest import sha256_hex

SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class OutputStoreError(RuntimeError):
    """Base error for output-store validation failures."""


class OutputConflictError(OutputStoreError):
    """A run/output pair already exists with different content."""


def safe_component(value: Any, field: str) -> str:
    if value is None or not str(value).strip():
        raise OutputStoreError(f"{field} is required")
    text = str(value).strip()
    if not SAFE_COMPONENT_RE.match(text) or ".." in text:
        raise OutputStoreError(f"{field} must be a safe path component: {text!r}")
    return text


def output_path(root: str | Path, run_id: str, output_kind: str) -> Path:
    base = Path(root).resolve()
    return (
        base
        / safe_component(run_id, "run_id")
        / f"{safe_component(output_kind, 'output_kind')}.json"
    )


def _validate_payload(payload: Any) -> None:
    if isinstance(payload, (str, bytes)) or not isinstance(payload, (Mapping, list)):
        raise OutputStoreError("payload must be a JSON object or list")


def build_stored_ref(
    root: str | Path,
    run_id: str,
    output_kind: str,
    content_hash: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    written: bool = False,
    existed: bool = False,
    would_write: bool = False,
) -> dict[str, Any]:
    base = Path(root).resolve()
    path = output_path(base, run_id, output_kind)
    return {
        "run_id": run_id,
        "output_kind": output_kind,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "storage_ref": path.relative_to(base).as_posix(),
        "content_hash": content_hash,
        "written": written,
        "existed": existed,
        "would_write": would_write,
    }


def store_output(
    payload: Any,
    *,
    root: str | Path,
    run_id: str,
    output_kind: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Store one payload; dry-run by default and never overwrite differing content."""
    _validate_payload(payload)
    path = output_path(root, run_id, output_kind)
    content_hash = sha256_hex(payload)
    ref_kwargs = {
        "root": root,
        "run_id": run_id,
        "output_kind": output_kind,
        "content_hash": content_hash,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise OutputStoreError(f"existing output is not readable JSON: {path}") from exc
        existing_hash = sha256_hex(existing)
        if existing_hash != content_hash:
            raise OutputConflictError(
                f"{ref_kwargs['run_id']}/{ref_kwargs['output_kind']} already exists "
                f"with content_hash {existing_hash}"
            )
        return build_stored_ref(**ref_kwargs, written=False, existed=True, would_write=False)

    if not write:
        return build_stored_ref(**ref_kwargs, written=False, existed=False, would_write=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return build_stored_ref(**ref_kwargs, written=True, existed=False, would_write=False)


def read_output(root: str | Path, run_id: str, output_kind: str) -> tuple[Any, dict[str, Any]]:
    """Read a stored payload and its content-hash ref."""
    path = output_path(root, run_id, output_kind)
    if not path.is_file():
        raise OutputStoreError(f"output not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise OutputStoreError(f"output is not readable JSON: {path}") from exc
    ref = build_stored_ref(
        root,
        run_id,
        output_kind,
        sha256_hex(payload),
        written=False,
        existed=True,
    )
    return payload, ref


def build_ledger_output_ref(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a stored-output ref into an ``audit.run_outputs`` payload."""
    for field in ("run_id", "output_kind", "storage_ref", "content_hash"):
        if not stored.get(field):
            raise OutputStoreError(f"stored ref missing {field}")
    return {
        "run_id": stored["run_id"],
        "output_kind": stored["output_kind"],
        "entity_type": stored.get("entity_type"),
        "entity_id": stored.get("entity_id"),
        "storage_ref": stored["storage_ref"],
        "content_hash": stored["content_hash"],
        "created_at_utc": stored.get("created_at_utc"),
        "metadata": {
            "store": "run_output_store/v1",
            "run_keyed": True,
            "written": bool(stored.get("written")),
            "existed": bool(stored.get("existed")),
        },
    }


def register_output_ref(conn, stored: Mapping[str, Any]) -> dict[str, Any]:
    """Insert a stored-output ref into the candidate ledger; caller owns the txn."""
    from .manifest_store import insert_run_outputs

    return insert_run_outputs(conn, stored["run_id"], [build_ledger_output_ref(stored)])
