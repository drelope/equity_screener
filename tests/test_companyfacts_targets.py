from unittest.mock import patch

from scripts import populate_companyfacts


class _Result:
    def mappings(self):
        return self

    def all(self):
        return []


class _Connection:
    def execute(self, *_args, **_kwargs):
        return _Result()


class _CursorConn:
    """Connection whose execute yields the given 1-tuples for any statement."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return iter(self.rows)


def test_existing_facts_ciks_collects_persisted_ciks():
    conn = _CursorConn([("0001332551",), ("0000948320",)])
    assert populate_companyfacts.existing_facts_ciks(conn) == {
        "0001332551",
        "0000948320",
    }


def test_preferred_facts_skips_already_stored_ciks():
    class _ResumableConn:
        def __init__(self):
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            self.commits += 1

        def execute(self, statement, _params=None):
            if "SELECT DISTINCT cik FROM raw.companyfacts" in str(statement):
                return iter([("0000000001",)])

            class _Mappings:
                def __init__(self, rows):
                    self._rows = rows

                def mappings(self):
                    return self

                def all(self):
                    return self._rows

            return _Mappings([
                {"cik": "0000000002", "ticker": "BBB", "title": "B Corp",
                 "security_id": "security-b"},
                {"cik": "0000000001", "ticker": "AAA", "title": "A Corp",
                 "security_id": "security-a"},
            ]).mappings()

    conn = _ResumableConn()
    fetched = []

    def _fake_ingest(_conn, cik, _entries, _stats):
        fetched.append(cik)

    with patch.object(populate_companyfacts, "engine") as engine, patch.object(
        populate_companyfacts, "_ingest_cik", side_effect=_fake_ingest
    ):
        engine.connect.return_value = conn
        populate_companyfacts.populate_preferred_companyfacts()

    assert fetched == ["0000000002"]
    assert conn.commits == 1


def test_companyfacts_targets_include_preferred_profile_rows():
    audited = [{"ticker": "AAA", "security_id": "security-a"}]
    profile = [{"ticker": "PFD", "security_id": "security-pfd"}]

    with patch.object(populate_companyfacts, "load_securities", return_value=audited), patch.object(
        populate_companyfacts, "load_ticker_profile_targets", return_value=profile
    ):
        targets = populate_companyfacts.load_companyfacts_targets(_Connection())

    assert {row["ticker"] for row in targets} == {"AAA", "PFD"}