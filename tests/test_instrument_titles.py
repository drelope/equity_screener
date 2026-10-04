"""pick_best_filing must choose the most recent filing in the preferred form tier.

Regression: a single ascending sort on (form_priority, filing_date) returned
the OLDEST annual report, so dei cover titles were parsed from decade-old
instances (or none at all when that old report predates XBRL).
"""

from scripts.populate_sec_instrument_titles import pick_best_filing


def _payload(accessions_forms_dates):
    rows = [
        {
            "accessionNumber": [a],
            "form": [f],
            "filingDate": [d],
            "isXBRL": [True],
            "primaryDocument": [f"{a}.htm"],
        }
        for a, f, d in accessions_forms_dates
    ]
    return _merge(rows)


def _merge(rows):
    keys = ("accessionNumber", "form", "filingDate", "isXBRL", "primaryDocument")
    out = {key: [row[key][0] for row in rows] for key in keys}
    return {"filings": {"recent": out}}


def test_prefers_most_recent_annual_report():
    payload = _payload(
        [
            ("0001294154-12-000054", "10-K", "2012-03-30"),
            ("0001193125-18-100000", "10-K", "2018-03-15"),
            ("0001104659-20-040000", "10-K", "2020-02-27"),
        ]
    )
    pick = pick_best_filing(payload)
    assert pick["accession"] == "0001104659-20-040000"
    assert pick["filing_date"] == "2020-02-27"


def test_prefers_annual_report_over_nearer_quarterly():
    payload = _payload(
        [
            ("0001193125-18-100000", "10-K", "2018-03-15"),
            ("0001104659-23-070000", "10-Q", "2023-11-06"),
        ]
    )
    pick = pick_best_filing(payload)
    assert pick["form"] == "10-K"
    assert pick["accession"] == "0001193125-18-100000"


def test_skips_non_xbrl_filings():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001294154-12-000054"],
                "form": ["8-K"],
                "filingDate": ["2024-01-01"],
                "isXBRL": [False],
                "primaryDocument": ["filing.htm"],
            }
        }
    }
    assert pick_best_filing(payload) is None


def test_empty_payload_returns_none():
    assert pick_best_filing({}) is None
    assert pick_best_filing(None) is None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result(self._rows)


def test_load_cik_universe_defaults_to_active_securities():
    from scripts.populate_sec_instrument_titles import load_cik_universe

    conn = _FakeConnection([{"cik": "0000320193"}])

    ciks = load_cik_universe(conn)

    assert ciks == ["0000320193"]
    assert "s.active = TRUE" in conn.statements[0]


def test_load_cik_universe_keeps_active_filter_with_explicit_cik():
    from scripts.populate_sec_instrument_titles import load_cik_universe

    conn = _FakeConnection()

    load_cik_universe(conn, cik="320193")

    assert "s.active = TRUE" in conn.statements[0]
    assert "s.cik = :cik" in conn.statements[0]
