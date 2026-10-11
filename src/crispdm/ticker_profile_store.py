"""Single write path for ``raw.ticker_profile``.

Every observation is first appended, as received, to ``raw.ticker_profile_load``
(the immutable landing history). ``raw.ticker_profile`` is then maintained as the
*latest* view per security using explicit column ownership:

* A writer declares the typed columns it is authoritative for (``owned_columns``).
  Those columns are overwritten with the new observation, including NULL, so a
  value that disappears from the source (or was mis-derived by an earlier run)
  is cleared instead of being preserved forever by ``COALESCE(new, old)``.
* Columns the writer does not own are left untouched, so one stage cannot erase
  another stage's evidence.
* ``raw_payload`` is a provider envelope (``openbb``, ``sec_xbrl``,
  ``sec_xbrl_scope``). Envelope keys present in the new payload replace the old
  ones wholesale; any other top-level key is legacy debris and is dropped.
* ``field_sources`` records which loader last set each owned column.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

PAYLOAD_ENVELOPE_KEYS = ("openbb", "sec_xbrl", "sec_xbrl_scope")
SEC_XBRL_SCOPE = "issuer_level_unallocated"

OPENBB_COLUMNS = ("sector", "industry")
NAME_PARSE_COLUMNS = (
    "security_type",
    "coupon_type",
    "coupon_rate",
    "fixed_period_end",
    "floating_spread",
    "tax_status",
    "call_date",
    "liquidation_preference",
)
PROFILE_COLUMNS = OPENBB_COLUMNS + NAME_PARSE_COLUMNS

COMBINABLE_PROVIDERS = ("SEC_XBRL", "OPENBB_YFINANCE", "SEC_XBRL+OPENBB_YFINANCE")


def envelope_payload(*, openbb=None, sec_xbrl=None, sec_xbrl_scope=None):
    """Build a provider envelope, omitting providers that returned nothing.

    An empty OpenBB response (network failure, offline run) must not replace a
    previously stored profile, so it is left out rather than written as ``{}``.
    """
    payload = {}
    if isinstance(openbb, dict) and openbb:
        payload["openbb"] = openbb
    if sec_xbrl is not None:
        payload["sec_xbrl"] = sec_xbrl
    if sec_xbrl_scope is not None:
        payload["sec_xbrl_scope"] = sec_xbrl_scope
    return payload


def _payload_dict(raw_payload):
    if raw_payload is None:
        return {}
    if isinstance(raw_payload, str):
        raw_payload = json.loads(raw_payload) if raw_payload.strip() else {}
    if not isinstance(raw_payload, dict):
        raise ValueError("raw_payload must be a JSON object")
    unknown = set(raw_payload) - set(PAYLOAD_ENVELOPE_KEYS)
    if unknown:
        raise ValueError(
            f"raw_payload must be a provider envelope {PAYLOAD_ENVELOPE_KEYS}; "
            f"got top-level keys {sorted(unknown)}"
        )
    return raw_payload


def payload_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _upsert_sql(owned_columns):
    assignments = [f"{column} = EXCLUDED.{column}" for column in owned_columns]
    assignments_sql = "".join(f"\n        {line}," for line in assignments)
    columns = ", ".join(PROFILE_COLUMNS)
    binds = ", ".join(f":{column}" for column in PROFILE_COLUMNS)
    return f"""
    INSERT INTO raw.ticker_profile AS current_profile
        (security_id, ticker, provider, {columns},
         raw_payload, field_sources, retrieved_at)
    VALUES (:security_id, :ticker, :provider, {binds},
            CAST(:raw_payload AS jsonb), CAST(:field_sources AS jsonb), now())
    ON CONFLICT (security_id) DO UPDATE SET
        ticker = EXCLUDED.ticker,
        provider = CASE
            WHEN current_profile.provider = EXCLUDED.provider THEN EXCLUDED.provider
            WHEN current_profile.provider IN {COMBINABLE_PROVIDERS!r}
             AND EXCLUDED.provider IN {COMBINABLE_PROVIDERS!r}
            THEN 'SEC_XBRL+OPENBB_YFINANCE'
            ELSE EXCLUDED.provider
        END,{assignments_sql}
        field_sources = COALESCE(current_profile.field_sources, '{{}}'::jsonb)
                        || EXCLUDED.field_sources,
        raw_payload = COALESCE((
            SELECT jsonb_object_agg(kept.key, kept.value)
            FROM jsonb_each(current_profile.raw_payload) AS kept(key, value)
            WHERE kept.key IN {PAYLOAD_ENVELOPE_KEYS!r}
        ), '{{}}'::jsonb) || EXCLUDED.raw_payload,
        retrieved_at = CASE WHEN CAST(:refreshed AS boolean) THEN now()
                            ELSE current_profile.retrieved_at END
    """


LOAD_SQL = f"""
INSERT INTO raw.ticker_profile_load
    (security_id, ticker, provider, loader, owned_columns, {", ".join(PROFILE_COLUMNS)},
     raw_payload, payload_hash, retrieved_at)
VALUES (:security_id, :ticker, :provider, :loader, CAST(:owned_columns AS text[]),
        {", ".join(f":{column}" for column in PROFILE_COLUMNS)},
        CAST(:raw_payload AS jsonb), :payload_hash, now())
"""


def upsert_ticker_profile(conn, row, *, loader, owned_columns, refreshed=True):
    """Append ``row`` to the load history and merge it into the latest table.

    ``row`` needs ``security_id``, ``ticker``, ``provider`` and ``raw_payload``
    (an envelope dict or its JSON text); missing profile columns are NULL.
    ``refreshed=False`` marks a DB-only correction: the existing
    ``retrieved_at`` (provider freshness) is kept instead of bumped.
    Returns the rowcount of the latest-table upsert.
    """
    owned = tuple(dict.fromkeys(owned_columns))
    unknown = set(owned) - set(PROFILE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown ticker_profile columns: {sorted(unknown)}")

    payload = _payload_dict(row.get("raw_payload"))
    params = {column: row.get(column) for column in PROFILE_COLUMNS}
    params.update(
        security_id=row["security_id"],
        ticker=row["ticker"],
        provider=row["provider"],
        loader=loader,
        refreshed=bool(refreshed),
        owned_columns="{" + ",".join(owned) + "}",
        raw_payload=json.dumps(payload, default=str),
        payload_hash=payload_hash(payload),
        field_sources=json.dumps({column: loader for column in owned}),
    )
    conn.execute(text(LOAD_SQL), params)
    result = conn.execute(text(_upsert_sql(owned)), params)
    return getattr(result, "rowcount", None)
