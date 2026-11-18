from scripts.check_manifest_ledger_integrity import inspect_ledger, main
from src.crispdm.run_manifest import canonical_json, sha256_hex


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def mappings(self):
        return FakeMappings(self._rows)


class FakeConn:
    def __init__(self, manifests, outputs):
        self.manifests = manifests
        self.outputs = outputs

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return FakeResult(scalar=True)
        if "FROM audit.run_manifests" in sql:
            return FakeResult(rows=self.manifests)
        if "FROM audit.run_outputs" in sql:
            return FakeResult(rows=self.outputs)
        raise AssertionError(f"unexpected SQL: {sql}")


def manifest():
    return {
        "run_id": "run-1",
        "run_type": "score",
        "status": "created",
        "created_at_utc": "2026-11-16T00:00:00+00:00",
        "parameters": {"as_of": "2026-11-15"},
        "inputs": {"snapshot": "snap-1"},
        "outputs": {"rows": 1},
        "environment": {"python": "3.11"},
    }


def manifest_row(overrides=None):
    value = manifest()
    row = {
        "run_id": value["run_id"],
        "status": value["status"],
        "manifest_hash": sha256_hex(value),
        "manifest_json": canonical_json(value),
        "parameters": canonical_json(value["parameters"]),
        "input_refs": canonical_json(value["inputs"]),
        "output_refs": canonical_json(value["outputs"]),
        "environment": canonical_json(value["environment"]),
    }
    row.update(overrides or {})
    return row


def output_row(run_id="run-1", output_id=1):
    return {
        "output_id": output_id,
        "run_id": run_id,
        "output_kind": "score",
        "storage_ref": "artifacts/score.parquet",
    }


def test_valid_ledger_passes():
    result = inspect_ledger(FakeConn([manifest_row()], [output_row()]))
    assert result["passed"] is True
    assert result["run_count"] == 1
    assert result["output_count"] == 1


def test_hash_mismatch_is_detected():
    row = manifest_row({"manifest_hash": "0" * 64})
    result = inspect_ledger(FakeConn([row], []))
    assert result["passed"] is False
    assert any("manifest_hash mismatch" in issue for issue in result["issues"])


def test_denormalized_drift_is_detected():
    row = manifest_row({"parameters": canonical_json({"as_of": "WRONG"})})
    result = inspect_ledger(FakeConn([row], []))
    assert any("parameters does not match" in issue for issue in result["issues"])


def test_orphan_output_is_detected():
    result = inspect_ledger(FakeConn([manifest_row()], [output_row(run_id="missing")]))
    assert any("missing parent manifest" in issue for issue in result["issues"])


def test_empty_storage_ref_is_detected():
    row = output_row()
    row["storage_ref"] = ""
    result = inspect_ledger(FakeConn([manifest_row()], [row]))
    assert any("empty storage_ref" in issue for issue in result["issues"])


def test_missing_ledger_raises(monkeypatch):
    import scripts.check_manifest_ledger_integrity as module

    monkeypatch.setattr(module, "ledger_available", lambda conn: False)
    try:
        inspect_ledger(FakeConn([], []))
    except Exception as exc:  # noqa: BLE001
        assert "candidate ledger missing" in str(exc)
    else:
        raise AssertionError("expected ManifestLedgerUnavailable")


def test_cli_refuses_shared_db_before_connecting(capsys):
    rc = main(["--dsn", "postgresql://u:p@localhost:5432/dividend"])
    assert rc == 2
    assert "shared/production-like" in capsys.readouterr().err
