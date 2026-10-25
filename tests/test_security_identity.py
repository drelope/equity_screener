"""Security identity is (cik, ticker, security_type); dividend is an attribute (V0092)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITERS = [
    ROOT / "scripts" / "populate_reference_tables.py",
    ROOT / "scripts" / "populate_raw_tables.py",
]


def test_no_writer_keys_an_identity_on_the_dividend_flag():
    for path in WRITERS:
        text = path.read_text(encoding="utf-8")
        assert "ON CONFLICT (cik, ticker, security_type, dividend)" not in text, path.name
        assert ":{classification['dividend']}\"" not in text, path.name
        assert ':{dividend}"' not in text, path.name


def test_identity_is_minted_without_the_dividend_flag_and_reuses_the_existing_row():
    text = (ROOT / "scripts" / "populate_reference_tables.py").read_text(encoding="utf-8")
    assert "dividend-equity:{sec['ticker'].upper()}:{cik}:{security_type}\"" in text
    assert "WHERE cik = :cik AND ticker = :ticker AND security_type = :type" in text


def test_schema_declares_the_identity_index_without_dividend():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    assert (
        "ux_security_cik_ticker_type\n  ON reference.securities (cik, ticker, security_type);"
        in schema
    )
