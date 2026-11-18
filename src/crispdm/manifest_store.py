"""Append-only run-manifest ledger persistence (RM-04/RM-05 draft).

The candidate schema lives in ``V0110_rm04_run_manifest_ledger.sql`` and is **not
applied or approved**. This module is an opt-in persistence path: it never creates
tables, never updates existing rows, and refuses to write unless the caller supplies
an open transaction and the ledger tables exist.

Every function takes an open SQLAlchemy connection and never commits; the caller owns
the transaction. Inserts use ``ON CONFLICT DO NOTHING`` so rerunning the same run is
idempotent. A conflicting payload for an existing ``run_id`` raises instead of
overwriting: the ledger is append-only by contract, even before a database trigger
or role model is approved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from .run_manifest import canonical_json, sha256_hex


class ManifestLedgerError(RuntimeError):
    """Base error for ledger availability/validation failures."""


class ManifestLedgerUnavailable(ManifestLedgerError):
    """The candidate ledger tables are not present on this target."""


class ManifestConflictError(ManifestLedgerError):
    """An existing run_id has a different manifest payload/hash."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ManifestLedgerError(f"{field} must be a mapping/object")
    return value


def validate_manifest_for_ledger(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise ManifestLedgerError("manifest must be a mapping/object")
    for field in ("run_id", "run_type", "created_at_utc"):
        value = manifest.get(field)
        if value is None or not str(value).strip():
            raise ManifestLedgerError(f"manifest missing required field: {field}")
    _as_mapping(manifest.get("parameters"), "parameters")
    _as_mapping(manifest.get("inputs"), "inputs")
    _as_mapping(manifest.get("outputs"), "outputs")
    _as_mapping(manifest.get("environment"), "environment")


def build_manifest_row(
    manifest: Mapping[str, Any],
    *,
    recorded_by: str | None = None,
) -> dict[str, Any]:
    """Build the ``audit.run_manifests`` parameter payload; no DB access."""
    validate_manifest_for_ledger(manifest)
    code = _as_mapping(manifest.get("code"), "code")
    return {
        "run_id": str(manifest["run_id"]),
        "run_type": str(manifest["run_type"]),
        "created_at_utc": str(manifest["created_at_utc"]),
        "resolved_as_of": manifest.get("resolved_as_of"),
        "code_sha": code.get("sha"),
        "code_dirty": code.get("dirty"),
        "git_branch": code.get("branch"),
        "parameters": canonical_json(_as_mapping(manifest.get("parameters"), "parameters")),
        "input_refs": canonical_json(_as_mapping(manifest.get("inputs"), "inputs")),
        "output_refs": canonical_json(_as_mapping(manifest.get("outputs"), "outputs")),
        "environment": canonical_json(_as_mapping(manifest.get("environment"), "environment")),
        "status": str(manifest.get("status") or "created"),
        "manifest_hash": sha256_hex(manifest),
        "manifest_json": canonical_json(manifest),
        "recorded_by": recorded_by,
    }


def build_output_rows(
    run_id: str,
    outputs: Sequence[Mapping[str, Any]] | None,
    *,
    recorded_at_utc: str | None = None,
) -> list[dict[str, Any]]:
    """Validate output refs and build ``audit.run_outputs`` parameter payloads."""
    if not outputs:
        return []
    if isinstance(outputs, (str, bytes)) or not isinstance(outputs, Sequence):
        raise ManifestLedgerError("outputs must be a list of objects")
    rows: list[dict[str, Any]] = []
    for index, output in enumerate(outputs):
        if not isinstance(output, Mapping):
            raise ManifestLedgerError(f"outputs[{index}] must be a mapping/object")
        output_kind = output.get("output_kind")
        storage_ref = output.get("storage_ref")
        if output_kind is None or not str(output_kind).strip():
            raise ManifestLedgerError(f"outputs[{index}] missing output_kind")
        if storage_ref is None or not str(storage_ref).strip():
            raise ManifestLedgerError(f"outputs[{index}] missing storage_ref")
        metadata = _as_mapping(output.get("metadata"), f"outputs[{index}].metadata")
        rows.append(
            {
                "run_id": run_id,
                "output_kind": str(output_kind),
                "entity_type": output.get("entity_type"),
                "entity_id": output.get("entity_id"),
                "storage_ref": str(storage_ref),
                "content_hash": output.get("content_hash"),
                "created_at_utc": output.get("created_at_utc") or recorded_at_utc or _utc_now_iso(),
                "metadata": canonical_json(metadata),
            }
        )
    return rows


def ledger_available(conn) -> bool:
    """Return True only when both candidate ledger tables exist."""
    row = conn.execute(
        text(
            """
            SELECT to_regclass('audit.run_manifests') IS NOT NULL
               AND to_regclass('audit.run_outputs') IS NOT NULL
            """
        )
    ).scalar()
    return bool(row)


def _require_ledger(conn) -> None:
    if not ledger_available(conn):
        raise ManifestLedgerUnavailable(
            "audit.run_manifests/audit.run_outputs are missing; "
            "apply/bless V0110 on an approved target first"
        )


def _existing_hash(conn, run_id: str) -> str | None:
    return conn.execute(
        text("SELECT manifest_hash FROM audit.run_manifests WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).scalar()


def insert_run_manifest(
    conn,
    manifest: Mapping[str, Any],
    *,
    recorded_by: str | None = None,
) -> dict[str, Any]:
    """Insert one manifest; idempotent on identical run_id/hash, conflict otherwise."""
    row = build_manifest_row(manifest, recorded_by=recorded_by)
    _require_ledger(conn)
    inserted = conn.execute(
        text(
            """
            INSERT INTO audit.run_manifests (
                run_id, run_type, created_at_utc, resolved_as_of, code_sha,
                code_dirty, git_branch, parameters, input_refs, output_refs,
                environment, status, manifest_hash, manifest_json, recorded_by
            ) VALUES (
                :run_id, :run_type, CAST(:created_at_utc AS timestamptz),
                :resolved_as_of, :code_sha, :code_dirty, :git_branch,
                CAST(:parameters AS jsonb), CAST(:input_refs AS jsonb),
                CAST(:output_refs AS jsonb), CAST(:environment AS jsonb),
                :status, :manifest_hash, CAST(:manifest_json AS jsonb), :recorded_by
            )
            ON CONFLICT (run_id) DO NOTHING
            RETURNING run_id
            """
        ),
        row,
    ).scalar()
    if inserted is None:
        existing = _existing_hash(conn, row["run_id"])
        if existing != row["manifest_hash"]:
            raise ManifestConflictError(
                f"run_id {row['run_id']!r} already exists with a different manifest_hash"
            )
    return {
        "run_id": row["run_id"],
        "manifest_hash": row["manifest_hash"],
        "inserted": inserted is not None,
    }


def insert_run_outputs(
    conn,
    run_id: str,
    outputs: Sequence[Mapping[str, Any]] | None,
    *,
    recorded_at_utc: str | None = None,
) -> dict[str, Any]:
    """Insert output refs idempotently; never updates existing rows."""
    rows = build_output_rows(run_id, outputs, recorded_at_utc=recorded_at_utc)
    if not rows:
        return {"requested": 0, "inserted": 0}
    _require_ledger(conn)
    inserted = 0
    for row in rows:
        output_id = conn.execute(
            text(
                """
                INSERT INTO audit.run_outputs (
                    run_id, output_kind, entity_type, entity_id, storage_ref,
                    content_hash, created_at_utc, metadata
                ) VALUES (
                    :run_id, :output_kind, :entity_type, :entity_id, :storage_ref,
                    :content_hash, CAST(:created_at_utc AS timestamptz),
                    CAST(:metadata AS jsonb)
                )
                ON CONFLICT (run_id, output_kind, storage_ref) DO NOTHING
                RETURNING output_id
                """
            ),
            row,
        ).scalar()
        if output_id is not None:
            inserted += 1
    return {"requested": len(rows), "inserted": inserted}


def persist_manifest(
    conn,
    manifest: Mapping[str, Any],
    *,
    outputs: Sequence[Mapping[str, Any]] | None = None,
    recorded_by: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Persist a manifest and optional output refs inside the caller's transaction.

    ``dry_run=True`` builds and validates the payload but performs no DB access.
    The caller must commit (or roll back) the transaction.
    """
    manifest_row = build_manifest_row(manifest, recorded_by=recorded_by)
    output_rows = build_output_rows(manifest_row["run_id"], outputs)
    if dry_run:
        return {
            "dry_run": True,
            "run_id": manifest_row["run_id"],
            "manifest_hash": manifest_row["manifest_hash"],
            "manifest_row": manifest_row,
            "output_rows": output_rows,
        }
    manifest_result = insert_run_manifest(conn, manifest, recorded_by=recorded_by)
    output_result = insert_run_outputs(conn, manifest_row["run_id"], outputs)
    return {
        "dry_run": False,
        "run_id": manifest_row["run_id"],
        "manifest_hash": manifest_row["manifest_hash"],
        "manifest_inserted": manifest_result["inserted"],
        "outputs_requested": output_result["requested"],
        "outputs_inserted": output_result["inserted"],
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def get_run_manifest(conn, run_id: str) -> dict[str, Any] | None:
    """Read one ledger manifest plus its recorded metadata; no writes."""
    _require_ledger(conn)
    row = (
        conn.execute(
            text(
                """
            SELECT run_id, run_type, created_at_utc, resolved_as_of, code_sha,
                   code_dirty, git_branch, parameters, input_refs, output_refs,
                   environment, status, manifest_hash, manifest_json,
                   recorded_at, recorded_by
            FROM audit.run_manifests
            WHERE run_id = :run_id
            """
            ),
            {"run_id": run_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    record = dict(row)
    record["parameters"] = _json_value(record.get("parameters"))
    record["input_refs"] = _json_value(record.get("input_refs"))
    record["output_refs"] = _json_value(record.get("output_refs"))
    record["environment"] = _json_value(record.get("environment"))
    record["manifest_json"] = _json_value(record.get("manifest_json"))
    return record


def get_run_outputs(conn, run_id: str) -> list[dict[str, Any]]:
    """Read run-keyed output refs ordered by insertion id; no writes."""
    _require_ledger(conn)
    rows = (
        conn.execute(
            text(
                """
            SELECT output_id, run_id, output_kind, entity_type, entity_id,
                   storage_ref, content_hash, created_at_utc, metadata, recorded_at
            FROM audit.run_outputs
            WHERE run_id = :run_id
            ORDER BY output_id
            """
            ),
            {"run_id": run_id},
        )
        .mappings()
        .all()
    )
    outputs = []
    for row in rows:
        record = dict(row)
        record["metadata"] = _json_value(record.get("metadata"))
        outputs.append(record)
    return outputs


def get_run_bundle(conn, run_id: str) -> dict[str, Any] | None:
    """Read a manifest and its outputs as one bundle; None when run_id is absent."""
    manifest = get_run_manifest(conn, run_id)
    if manifest is None:
        return None
    outputs = get_run_outputs(conn, run_id)
    return {
        "run_id": run_id,
        "manifest": manifest,
        "outputs": outputs,
        "output_count": len(outputs),
    }
