"""The dividend universe: a recent XBRL tag, or a payment we have actually observed."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from scripts import populate_raw_tables as prt
from src.crispdm import dividend_universe
from src.crispdm.config import Settings
from src.crispdm.dividend_universe import observed_payer_keys


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class _Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        return _Rows(self.rows)


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setattr(dividend_universe.settings, "enforce_dividend_recency", True)
    monkeypatch.setattr(dividend_universe.settings, "dividend_recency_days", 548)


def test_recency_is_enforced_by_default():
    assert Settings.model_fields["enforce_dividend_recency"].default is True


def test_observed_payers_are_the_ciks_and_tickers_with_a_payment_in_the_window(enforced):
    conn = _Conn([("0000000001", "AAA"), ("0000000002", "BBB-PA")])

    keys = observed_payer_keys(conn, today=date(2026, 10, 6))

    assert keys == {("0000000001", "AAA"), ("0000000002", "BBB-PA")}
    sql, params = conn.calls[0]
    assert params == {"since": date(2026, 10, 6) - timedelta(days=548), "today": date(2026, 10, 6)}
    assert "d.amount > 0" in sql, "a zero or negative amount is not a payment"
    assert "BETWEEN :since AND :today" in sql, "a future-dated period end is not a payment yet"


def test_nothing_is_observed_when_recency_is_not_enforced(monkeypatch):
    monkeypatch.setattr(dividend_universe.settings, "enforce_dividend_recency", False)
    conn = _Conn([("0000000001", "AAA")])

    assert observed_payer_keys(conn) == set()
    assert conn.calls == [], "off means the legacy rule exactly: no query, no override"


# --- stage 0 applies it ------------------------------------------------------------

_STALE = {
    "security_types": ["common stock"],
    "dividend": False,
    "security_titles": ["Acme"],
    "security_facts": [],
    "dividend_facts": [],
    "status": "available",
}


class _Scan:
    """Serves the scan's lookups: a stored payload for every CIK, no instrument titles."""

    def __init__(self):
        self.commits = 0

    def execute(self, stmt, params=None):
        # An identity lookup on reference.securities finds no existing row, so the
        # id is minted from (ticker, cik, security_type) as for a new security.
        is_identity_lookup = "reference.securities" in str(stmt)

        class _Result:
            def mappings(self):
                return iter([])

            def scalar(self):
                return None if is_identity_lookup else {"entityName": "Acme"}

        return _Result()

    def commit(self):
        self.commits += 1


def _scan(classification, observed):
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    cache = []
    with (
        patch.object(prt, "stored_facts_retrieved_at", return_value={"0000000001": recent}),
        patch.object(prt, "engine") as eng,
        patch.object(prt, "classify_companyfacts", return_value=classification),
        patch.object(prt, "observed_payer_keys", return_value=observed),
        patch.object(
            prt,
            "_load_raw_tickers",
            return_value=[{"cik": "0000000001", "ticker": "AAA", "title": "Acme"}],
        ),
        patch.object(
            prt, "_persist_classification_cache", side_effect=lambda c, e: cache.extend(e)
        ),
    ):
        eng.connect.return_value.__enter__.return_value = _Scan()
        payers = prt._identify_dividend_payers(reuse_max_age_days=5)
    return payers, cache


def test_a_stale_tag_with_an_observed_payment_stays_a_payer():
    payers, _ = _scan(_STALE, {("0000000001", "AAA")})

    (payer,) = payers
    assert payer["classification"]["dividend"] is True
    (security_id,) = payer["security_ids"].values()
    assert security_id is not None


def test_a_stale_tag_with_no_observed_payment_is_not_a_payer():
    payers, _ = _scan(_STALE, set())
    assert payers == []


def test_a_recent_tag_needs_no_observed_payment():
    payers, _ = _scan(dict(_STALE, dividend=True), set())
    assert len(payers) == 1


def test_the_override_does_not_rewrite_the_cached_classification():
    """The cache records what the filings say; the override is a per-security decision."""
    _, cache = _scan(_STALE, {("0000000001", "AAA")})

    ((_, _, _, cached),) = cache
    assert cached["dividend"] is False


def test_the_observed_payment_is_matched_on_cik_and_ticker_not_ticker_alone():
    payers, _ = _scan(_STALE, {("0000000099", "AAA")})
    assert payers == []


def test_the_security_id_of_an_overridden_payer_matches_the_one_stage_1_derives():
    """Stage 1 hashes the flag it resolved; a mismatch would mint a duplicate row."""
    import uuid

    payers, _ = _scan(_STALE, {("0000000001", "AAA")})
    (payer,) = payers
    (stage0_id,) = payer["security_ids"].values()
    security_type = payer["security_types"][0]

    stage1_id = uuid.uuid5(uuid.NAMESPACE_URL, f"dividend-equity:AAA:0000000001:{security_type}")

    assert stage0_id == stage1_id


# --- live data -----------------------------------------------------------------------


def _live_engine():
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM raw.dividend_data LIMIT 1")
        return engine
    except Exception:  # pragma: no cover
        return None


@pytest.mark.skipif(_live_engine() is None, reason="no live database")
def test_the_override_query_runs_against_the_real_schema(enforced):
    with _live_engine().connect() as conn:
        keys = observed_payer_keys(conn)

    assert keys, "the stored series has recent payments"
    assert all(isinstance(cik, str) and isinstance(ticker, str) for cik, ticker in keys if cik)
