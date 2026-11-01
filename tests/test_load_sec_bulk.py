import io
import json
import zipfile

from scripts.load_sec_bulk import changed_payloads
from scripts.populate_companyfacts import payload_hash


def _zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, json.dumps(payload))
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def test_only_new_or_changed_tracked_ciks_are_yielded():
    same, changed, new = {"v": 1}, {"v": 2}, {"v": 3}
    archive = _zip(
        {
            "CIK0000000001.json": same,
            "CIK0000000002.json": changed,
            "CIK0000000003.json": new,
            "CIK0000000004.json": {"v": 4},
        }
    )
    stored = {"0000000001": payload_hash(same), "0000000002": "stale"}

    got = {
        cik: digest
        for cik, _payload, digest in changed_payloads(
            archive, stored, {"0000000001", "0000000002", "0000000003"}
        )
    }

    assert got == {"0000000002": payload_hash(changed), "0000000003": payload_hash(new)}


def test_overflow_pages_and_unrelated_members_are_ignored():
    archive = _zip(
        {
            "CIK0000000001-submissions-001.json": {"v": 1},
            "README.txt": {"v": 1},
            "CIK0000000001.json": {"v": 1},
        }
    )

    got = [cik for cik, _, _ in changed_payloads(archive, {}, {"0000000001"})]

    assert got == ["0000000001"]


def test_an_unchanged_archive_yields_nothing():
    payload = {"v": 1}
    archive = _zip({"CIK0000000001.json": payload})

    assert not list(
        changed_payloads(archive, {"0000000001": payload_hash(payload)}, {"0000000001"})
    )


def test_unchanged_ciks_are_reported_for_verification():
    same, changed = {"v": 1}, {"v": 2}
    archive = _zip({"CIK0000000001.json": same, "CIK0000000002.json": changed})
    unchanged = []

    list(
        changed_payloads(
            archive,
            {"0000000001": payload_hash(same), "0000000002": "stale"},
            {"0000000001", "0000000002"},
            unchanged,
        )
    )

    assert unchanged == ["0000000001"]


def test_marking_verified_updates_only_the_timestamp(monkeypatch):
    from scripts import load_sec_bulk

    statements = []

    class _Conn:
        def execute(self, statement, params=None):
            statements.append((str(statement), params))

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(load_sec_bulk.engine, "begin", lambda: _Begin(), raising=False)

    assert load_sec_bulk.mark_verified("raw.sec_submissions", ["1", "2"]) == 2
    sql, params = statements[0]
    assert "SET retrieved_at = now()" in sql and "raw_payload" not in sql
    assert params == {"ciks": ["1", "2"]}
    assert load_sec_bulk.mark_verified("raw.sec_submissions", []) == 0
