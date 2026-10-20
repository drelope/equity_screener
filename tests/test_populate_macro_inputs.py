import sys
from datetime import date

from scripts import populate_macro_inputs


class _FakeConnection:
    def __init__(self):
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_args):
        return False


class _Engine:
    def __init__(self):
        self.conn = _FakeConnection()

    def begin(self):
        return _Begin(self.conn)


def _row(series_id="SOFR", value=3.9, unit="percent", source="FRED"):
    return {
        "series_id": series_id,
        "observation_date": date(2026, 10, 20),
        "value": value,
        "unit": unit,
        "source": source,
        "provider": "economy.fred_series",
    }


def test_upsert_series_writes_every_column_with_conflict_update():
    conn = _FakeConnection()

    assert populate_macro_inputs.upsert_series(conn, _row()) == 1

    sql = conn.statements[0]
    assert "INSERT INTO raw.macro_series" in sql
    assert "ON CONFLICT (series_id, observation_date)" in sql
    assert "EXCLUDED.value" in sql
    assert conn.params[0]["series_id"] == "SOFR"
    assert conn.params[0]["source"] == "FRED"


def test_upsert_sector_writes_weight_with_conflict_update():
    conn = _FakeConnection()
    row = {
        "symbol": "PFF",
        "sector": "Financial Services",
        "value": 0.4705,
        "source": "FMP",
    }

    assert populate_macro_inputs.upsert_sector(conn, row) == 1

    sql = conn.statements[0]
    assert "INSERT INTO raw.macro_etf_sectors" in sql
    assert "ON CONFLICT (symbol, sector)" in sql
    assert conn.params[0]["weight"] == 0.4705


def test_populate_macro_inputs_upserts_series_and_sector_rows(monkeypatch):
    rows = [_row(), _row("VIX", 17.31, "index points", "FMP")]
    sectors = [{"symbol": "PFF", "sector": "Financial Services", "value": 0.4705, "source": "FMP"}]
    stats_in = {"attempted": 3, "skipped": 0, "errors": 0, "empty": 0}
    monkeypatch.setattr(
        populate_macro_inputs,
        "collect_rows",
        lambda **kwargs: (rows, sectors, dict(stats_in)),
    )
    engine = _Engine()
    monkeypatch.setattr(populate_macro_inputs, "engine", engine)

    stats = populate_macro_inputs.populate_macro_inputs(lookback_days=10)

    assert stats["written"] == 3
    statements = engine.conn.statements
    assert sum("raw.macro_series" in sql for sql in statements) == 2
    assert sum("raw.macro_etf_sectors" in sql for sql in statements) == 1
    assert all(
        param["observation_date"] == date(2026, 10, 20)
        for param in engine.conn.params
        if param and "series_id" in param
    )


def test_main_reports_failure_when_work_was_attempted_and_nothing_written(monkeypatch):
    monkeypatch.setattr(
        populate_macro_inputs,
        "populate_macro_inputs",
        lambda **kwargs: {"attempted": 5, "written": 0, "skipped": 0, "errors": 2, "empty": 1},
    )
    monkeypatch.setattr(sys, "argv", ["populate_macro_inputs"])

    assert populate_macro_inputs.main() == 1


def test_main_succeeds_when_the_run_had_nothing_to_do(monkeypatch):
    monkeypatch.setattr(
        populate_macro_inputs,
        "populate_macro_inputs",
        lambda **kwargs: {"attempted": 0, "written": 0, "skipped": 37, "errors": 0, "empty": 0},
    )
    monkeypatch.setattr(sys, "argv", ["populate_macro_inputs"])

    assert populate_macro_inputs.main() == 0
