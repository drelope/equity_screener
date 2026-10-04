from types import SimpleNamespace

import pytest

from scripts import populate_reference_tables


class _Result:
    def __init__(self, *, rows=None, scalar=None, first=None):
        self.rows = rows or []
        self.scalar_value = scalar
        self.first_value = first

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_value

    def scalar(self):
        return self.scalar_value


class _Connection:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return self.results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_stale_security_with_children_is_deactivated_and_retained():
    conn = _Connection(
        [
            _Result(
                rows=[
                    {
                        "security_id": "stale-security",
                        "security_type": "common_stock",
                        "dividend": False,
                    }
                ]
            ),
            _Result(scalar=True),
            _Result(),
        ]
    )
    log = {"deleted": 0, "cascaded": 0, "deactivated_with_children": []}

    populate_reference_tables._reconcile_instrument_rows(
        conn,
        "ABR-PD",
        "0001253986",
        "preferred stock",
        True,
        log,
    )

    assert log["deleted"] == 0
    assert log["deactivated_with_children"] == [("ABR-PD", "common_stock")]
    assert "SET active = FALSE" in conn.statements[2][0]


def test_limited_reference_run_skips_global_identity_query(monkeypatch):
    conn = _Connection([_Result()])
    monkeypatch.setattr(
        populate_reference_tables,
        "engine",
        SimpleNamespace(begin=lambda: conn),
    )

    populate_reference_tables.validate_securities_reference_fk(
        check_active_identity_duplicates=False
    )

    assert len(conn.statements) == 1
    assert "VALIDATE CONSTRAINT fk_securities_company_ticker" in conn.statements[0][0]


def test_full_reference_run_stops_on_duplicate_active_identity(monkeypatch):
    conn = _Connection([_Result(first={"cik": "0001253986", "ticker": "ABR-PD", "active_rows": 2})])
    monkeypatch.setattr(
        populate_reference_tables,
        "engine",
        SimpleNamespace(begin=lambda: conn),
    )

    with pytest.raises(RuntimeError, match="Multiple active reference.securities rows"):
        populate_reference_tables.validate_securities_reference_fk()

    assert len(conn.statements) == 1
