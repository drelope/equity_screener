import json

import pytest

from scripts.persist_run_output import main as persist_main
from src.crispdm.output_store import (
    OutputConflictError,
    OutputStoreError,
    build_ledger_output_ref,
    read_output,
    safe_component,
    store_output,
)


def test_safe_component_rejects_traversal():
    assert safe_component("run-1", "run_id") == "run-1"
    with pytest.raises(OutputStoreError):
        safe_component("../etc", "run_id")
    with pytest.raises(OutputStoreError):
        safe_component("", "run_id")


def test_dry_run_does_not_write(tmp_path):
    ref = store_output({"score": 1}, root=tmp_path, run_id="run-1", output_kind="score")
    assert ref["would_write"] is True
    assert ref["written"] is False
    assert not (tmp_path / "run-1" / "score.json").exists()


def test_write_is_idempotent_and_conflict_safe(tmp_path):
    payload = {"score": 1}
    first = store_output(payload, root=tmp_path, run_id="run-1", output_kind="score", write=True)
    assert first["written"] is True
    second = store_output(
        dict(payload), root=tmp_path, run_id="run-1", output_kind="score", write=True
    )
    assert second["existed"] is True
    assert second["written"] is False
    assert second["content_hash"] == first["content_hash"]
    with pytest.raises(OutputConflictError):
        store_output({"score": 2}, root=tmp_path, run_id="run-1", output_kind="score", write=True)


def test_read_output_returns_payload_and_hash(tmp_path):
    stored = store_output(
        {"report": "ok"}, root=tmp_path, run_id="run-2", output_kind="report", write=True
    )
    payload, ref = read_output(tmp_path, "run-2", "report")
    assert payload == {"report": "ok"}
    assert ref["content_hash"] == stored["content_hash"]


def test_ledger_ref_conversion(tmp_path):
    stored = store_output(
        {"ai": 1},
        root=tmp_path,
        run_id="run-3",
        output_kind="ai_note",
        entity_type="security",
        entity_id="s1",
        write=True,
    )
    ledger = build_ledger_output_ref(stored)
    assert ledger["run_id"] == "run-3"
    assert ledger["storage_ref"] == "run-3/ai_note.json"
    assert ledger["metadata"]["run_keyed"] is True
    assert "written" in ledger["metadata"]


def test_cli_dry_run_and_write(tmp_path):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"score": 0.5}), encoding="utf-8")
    root = tmp_path / "store"
    assert (
        persist_main(
            [
                "--payload",
                str(payload),
                "--run-id",
                "r1",
                "--output-kind",
                "score",
                "--root",
                str(root),
            ]
        )
        == 0
    )
    assert not root.exists()
    assert (
        persist_main(
            [
                "--payload",
                str(payload),
                "--run-id",
                "r1",
                "--output-kind",
                "score",
                "--root",
                str(root),
                "--write",
            ]
        )
        == 2
    )
    assert (
        persist_main(
            [
                "--payload",
                str(payload),
                "--run-id",
                "r1",
                "--output-kind",
                "score",
                "--root",
                str(root),
                "--write",
                "--i-understand-run-output-write",
            ]
        )
        == 0
    )
    assert (root / "r1" / "score.json").is_file()


def test_cli_conflict_returns_1(tmp_path, capsys):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"v": 1}), encoding="utf-8")
    root = tmp_path / "store"
    args = [
        "--payload",
        str(payload),
        "--run-id",
        "r1",
        "--output-kind",
        "score",
        "--root",
        str(root),
        "--write",
        "--i-understand-run-output-write",
    ]
    assert persist_main(args) == 0
    payload.write_text(json.dumps({"v": 2}), encoding="utf-8")
    assert persist_main(args) == 1
    assert "already exists" in capsys.readouterr().err
