import json

from scripts.persist_run_manifest import main as cli_main
from scripts.show_run_ledger import main as show_main
from src.crispdm.manifest_store import (
    ManifestConflictError,
    ManifestLedgerError,
    ManifestLedgerUnavailable,
    build_manifest_row,
    build_output_rows,
    get_run_bundle,
    get_run_manifest,
    get_run_outputs,
    persist_manifest,
)
from src.crispdm.run_manifest import build_run_manifest, sha256_hex


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class NoLedgerConn:
    def execute(self, statement, params=None):
        assert "to_regclass" in str(statement)
        return FakeResult(False)


def sample_manifest(**overrides):
    payload = {
        "run_type": "score",
        "run_id": "run-1",
        "created_at_utc": "2026-11-16T00:00:00+00:00",
        "code_sha": "abc123",
        "code_dirty": False,
        "config": {"model_version": "v1"},
        "parameters": {"as_of": "2026-11-15"},
        "inputs": {"snapshot": "snap-1"},
        "outputs": {"rows": 10},
        "resolved_as_of": "2026-11-15",
        "environment": {"python": "3.11"},
    }
    payload.update(overrides)
    return build_run_manifest(**payload)


def test_build_manifest_row_maps_ledger_columns():
    manifest = sample_manifest()
    row = build_manifest_row(manifest, recorded_by="test")
    assert row["run_id"] == "run-1"
    assert row["run_type"] == "score"
    assert row["manifest_hash"] == sha256_hex(manifest)
    assert json.loads(row["manifest_json"]) == manifest
    assert json.loads(row["parameters"]) == {"as_of": "2026-11-15"}
    assert row["recorded_by"] == "test"


def test_build_manifest_row_requires_run_identity():
    manifest = sample_manifest()
    del manifest["run_id"]
    try:
        build_manifest_row(manifest)
    except ManifestLedgerError as exc:
        assert "run_id" in str(exc)
    else:
        raise AssertionError("expected ManifestLedgerError")


def test_build_output_rows_requires_storage_ref():
    rows = build_output_rows(
        "run-1",
        [{"output_kind": "score", "storage_ref": "artifacts/score.parquet"}],
    )
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["output_kind"] == "score"
    try:
        build_output_rows("run-1", [{"output_kind": "score"}])
    except ManifestLedgerError as exc:
        assert "storage_ref" in str(exc)
    else:
        raise AssertionError("expected ManifestLedgerError")


def test_dry_run_does_not_require_connection():
    manifest = sample_manifest()
    result = persist_manifest(
        None,
        manifest,
        outputs=[{"output_kind": "score", "storage_ref": "artifacts/score.parquet"}],
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["run_id"] == "run-1"
    assert len(result["output_rows"]) == 1


def test_missing_ledger_fails_closed():
    try:
        persist_manifest(NoLedgerConn(), sample_manifest(), dry_run=False)
    except ManifestLedgerUnavailable as exc:
        assert "audit.run_manifests" in str(exc)
    else:
        raise AssertionError("expected ManifestLedgerUnavailable")


def test_conflict_error_is_distinct():
    assert issubclass(ManifestConflictError, ManifestLedgerError)


def test_cli_dry_run_prints_plan(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(sample_manifest()), encoding="utf-8")
    rc = cli_main(["--manifest", str(manifest_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["dry_run"] is True
    assert payload["run_id"] == "run-1"


def test_cli_persist_requires_acknowledgement(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(sample_manifest()), encoding="utf-8")
    rc = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--dsn",
            "postgresql://u:p@localhost:5432/rehearsal",
            "--persist",
        ]
    )
    assert rc == 2
    assert "i-understand-ledger-write" in capsys.readouterr().err


def test_cli_refuses_shared_db_name_before_connecting(tmp_path, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(sample_manifest()), encoding="utf-8")
    rc = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--dsn",
            "postgresql://u:p@localhost:5432/dividend",
            "--persist",
            "--i-understand-ledger-write",
        ]
    )
    assert rc == 2
    assert "shared/production-like" in capsys.readouterr().err


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class LedgerReadResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return FakeMappings(self._rows)


class ReadConn:
    def __init__(self, manifest_row=None, output_rows=None):
        self.manifest_row = manifest_row
        self.output_rows = output_rows or []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return LedgerReadResult(scalar=True)
        if "FROM audit.run_manifests" in sql:
            return LedgerReadResult(rows=[self.manifest_row] if self.manifest_row else [])
        if "FROM audit.run_outputs" in sql:
            return LedgerReadResult(rows=self.output_rows)
        raise AssertionError(f"unexpected SQL: {sql}")


def ledger_manifest_row():
    return {
        "run_id": "run-1",
        "run_type": "score",
        "created_at_utc": "2026-11-16T00:00:00+00:00",
        "resolved_as_of": "2026-11-15",
        "code_sha": "abc123",
        "code_dirty": False,
        "git_branch": None,
        "parameters": {"as_of": "2026-11-15"},
        "input_refs": {"snapshot": "snap-1"},
        "output_refs": {"rows": 10},
        "environment": {"python": "3.11"},
        "status": "created",
        "manifest_hash": "hash-1",
        "manifest_json": {"run_id": "run-1", "run_type": "score"},
        "recorded_at": "2026-11-16T00:01:00+00:00",
        "recorded_by": "agent",
    }


def test_get_run_manifest_parses_json_fields():
    conn = ReadConn(manifest_row=ledger_manifest_row())
    manifest = get_run_manifest(conn, "run-1")
    assert manifest["run_id"] == "run-1"
    assert manifest["parameters"] == {"as_of": "2026-11-15"}
    assert manifest["manifest_json"]["run_type"] == "score"


def test_get_run_manifest_returns_none_when_absent():
    assert get_run_manifest(ReadConn(), "missing") is None


def test_get_run_outputs_parses_metadata():
    conn = ReadConn(
        manifest_row=ledger_manifest_row(),
        output_rows=[
            {
                "output_id": 1,
                "run_id": "run-1",
                "output_kind": "score",
                "entity_type": None,
                "entity_id": None,
                "storage_ref": "artifacts/score.parquet",
                "content_hash": "deadbeef",
                "created_at_utc": "2026-11-16T00:00:00+00:00",
                "metadata": {"rows": 10},
                "recorded_at": "2026-11-16T00:01:00+00:00",
            }
        ],
    )
    outputs = get_run_outputs(conn, "run-1")
    assert outputs[0]["storage_ref"] == "artifacts/score.parquet"
    assert outputs[0]["metadata"] == {"rows": 10}


def test_get_run_bundle_returns_manifest_and_outputs():
    conn = ReadConn(
        manifest_row=ledger_manifest_row(),
        output_rows=[
            {"output_id": 1, "run_id": "run-1", "output_kind": "score", "storage_ref": "x"}
        ],
    )
    bundle = get_run_bundle(conn, "run-1")
    assert bundle["run_id"] == "run-1"
    assert bundle["output_count"] == 1
    assert bundle["manifest"]["manifest_hash"] == "hash-1"


def test_get_run_bundle_returns_none_for_missing_run():
    assert get_run_bundle(ReadConn(), "missing") is None


def test_show_cli_refuses_shared_db_before_connecting(capsys):
    rc = show_main(
        [
            "--run-id",
            "run-1",
            "--dsn",
            "postgresql://u:p@localhost:5432/dividend",
        ]
    )
    assert rc == 2
    assert "shared/production-like" in capsys.readouterr().err
