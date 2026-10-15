from unittest.mock import patch

from scripts import populate_sec_documents


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _FakeConnection:
    """Returns a canned chunk per query, keyed by the keyset cursor sent."""

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.chunks.pop(0) if self.chunks else [])


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_args):
        return False


class _Engine:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        return _Begin(self.conn)

    def connect(self):
        return _Begin(self.conn)


def _row(ticker, security_id):
    return {
        "ticker": ticker,
        "security_id": security_id,
        "cik": "0000320193",
        "raw_payload": {"facts": {}},
    }


def test_load_companyfacts_applies_dividend_and_ticker_filters():
    conn = _FakeConnection()

    populate_sec_documents.load_companyfacts(conn, tickers=["aapl", "ko"])

    sql = conn.statements[0]
    assert "s.dividend = TRUE" in sql
    assert "s.active = TRUE" in sql
    assert "UPPER(s.ticker) = ANY(:tickers)" in sql
    assert conn.params[0] == {"tickers": ["AAPL", "KO"]}


def test_load_companyfacts_can_include_non_dividend_securities():
    conn = _FakeConnection()

    populate_sec_documents.load_companyfacts(conn, dividend_only=False)

    assert "s.dividend = TRUE" not in conn.statements[0]


def test_load_companyfacts_bounds_each_statement_with_a_keyset_cursor():
    conn = _FakeConnection()

    populate_sec_documents.load_companyfacts(
        conn, after=("AAPL", "11111111-1111-1111-1111-111111111111"), limit=50
    )

    sql = conn.statements[0]
    assert "(s.ticker, s.security_id) > (:after_ticker, :after_security_id)" in sql
    assert "ORDER BY s.ticker, s.security_id" in sql
    assert "LIMIT :limit" in sql
    assert conn.params[0]["after_ticker"] == "AAPL"
    assert conn.params[0]["limit"] == 50


def test_iter_companyfacts_pages_until_a_chunk_comes_back_empty():
    first = [_row("AAPL", "id-1"), _row("ABCL", "id-2")]
    second = [_row("ABCL", "id-3")]
    conn = _FakeConnection([first, second, []])

    rows = list(populate_sec_documents.iter_companyfacts(conn, chunk_size=2))

    assert [row["security_id"] for row in rows] == ["id-1", "id-2", "id-3"]
    assert len(conn.statements) == 3
    assert "after_ticker" not in conn.params[0]
    assert conn.params[1]["after_ticker"] == "ABCL"
    assert conn.params[1]["after_security_id"] == "id-2"
    assert conn.params[2]["after_ticker"] == "ABCL"
    assert conn.params[2]["after_security_id"] == "id-3"
    assert conn.params[2]["limit"] == 2


def test_populate_concept_groups_upserts_every_row_from_the_paged_loader():
    conn = _FakeConnection(
        [
            [
                {
                    "security_id": "11111111-1111-1111-1111-111111111111",
                    "cik": "0000320193",
                    "ticker": "AAPL",
                    "raw_payload": {
                        "facts": {
                            "us-gaap": {
                                "CommonStockDividendsPerShareDeclared": {},
                                "Assets": {},
                            }
                        }
                    },
                }
            ],
            [],
        ]
    )

    with patch("scripts.populate_sec_documents.engine", _Engine(conn)):
        scanned, updated, errors = populate_sec_documents.populate_concept_groups()

    insert_indexes = [
        i for i, sql in enumerate(conn.statements) if "INSERT INTO raw.sec_documents" in sql
    ]
    assert (scanned, updated, errors) == (1, 1, 0)
    assert len(insert_indexes) == 1
    assert (
        "CommonStockDividendsPerShareDeclared" in conn.params[insert_indexes[0]]["concept_groups"]
    )
    upsert_sql = conn.statements[insert_indexes[0]]
    assert "raw.sec_documents.content_hash IS DISTINCT FROM EXCLUDED.content_hash" in upsert_sql
    assert "ELSE raw.sec_documents.concept_groups END" in upsert_sql
