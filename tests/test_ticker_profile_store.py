import json

import pytest

from src.crispdm import ticker_profile_store as store


class _Conn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))

        class _R:
            rowcount = 1

        return _R()


def _row(**overrides):
    row = {"security_id": "sid-1", "ticker": "AAA", "provider": "SEC_XBRL", "raw_payload": {}}
    row.update(overrides)
    return row


def test_envelope_omits_an_empty_openbb_response():
    assert store.envelope_payload(openbb={}) == {}
    assert store.envelope_payload(openbb={"a": 1}, sec_xbrl_scope="x") == {
        "openbb": {"a": 1},
        "sec_xbrl_scope": "x",
    }


def test_a_flat_legacy_payload_is_rejected():
    with pytest.raises(ValueError, match="provider envelope"):
        store.upsert_ticker_profile(
            _Conn(), _row(raw_payload={"symbol": "AAA"}), loader="t", owned_columns=()
        )


def test_unknown_owned_column_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        store.upsert_ticker_profile(_Conn(), _row(), loader="t", owned_columns=("bogus",))


def test_load_history_is_appended_before_the_latest_upsert():
    conn = _Conn()
    payload = {"openbb": {"symbol": "AAA"}}

    count = store.upsert_ticker_profile(
        conn, _row(raw_payload=payload), loader="loader-x", owned_columns=("coupon_rate",)
    )

    assert count == 1
    (load_sql, load_params), (upsert_sql, _) = conn.statements
    assert "INSERT INTO raw.ticker_profile_load" in load_sql
    assert "INSERT INTO raw.ticker_profile AS current_profile" in upsert_sql
    assert load_params["owned_columns"] == "{coupon_rate}"
    assert load_params["payload_hash"] == store.payload_hash(payload)
    assert json.loads(load_params["field_sources"]) == {"coupon_rate": "loader-x"}


def test_only_owned_columns_are_overwritten_and_none_are_coalesced():
    sql = store._upsert_sql(("coupon_rate", "call_date"))

    assert "coupon_rate = EXCLUDED.coupon_rate" in sql
    assert "call_date = EXCLUDED.call_date" in sql
    assert "sector = EXCLUDED.sector" not in sql
    assert "liquidation_preference = EXCLUDED" not in sql
    assert "COALESCE(EXCLUDED." not in sql


def test_payload_merge_keeps_only_envelope_keys_from_the_current_row():
    sql = store._upsert_sql(())

    assert "WHERE kept.key IN ('openbb', 'sec_xbrl', 'sec_xbrl_scope')" in sql
    assert "|| EXCLUDED.raw_payload" in sql


def test_payload_hash_is_key_order_independent():
    assert store.payload_hash({"a": 1, "b": 2}) == store.payload_hash({"b": 2, "a": 1})


def test_db_only_corrections_keep_provider_freshness():
    sql = " ".join(store._upsert_sql(("coupon_rate",)).split())

    assert "WHEN CAST(:refreshed AS boolean) THEN now() ELSE current_profile.retrieved_at" in sql
