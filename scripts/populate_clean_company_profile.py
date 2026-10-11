"""Build clean company-profile, officer and corporate-action tables from raw OpenBB profiles.

Company scalars are stored in clean.company_profile; each company_officers
entry is stored in clean.company_officer and each corporate_actions entry in
clean.corporate_action, all rebuilt in one transaction. The 52_week_change
source key is mapped to pct_change_52w, epoch fields are converted to UTC
dates/timestamps, Infinity/NaN numerics load as NULL (listed in
non_finite_fields), and missing compensation remains NULL.

Mapping manifest: every OpenBB key is either a typed column (directly or via
SOURCE_KEY_RENAMES), a nested array handled by NESTED_SOURCE_KEYS, or an
unmapped scalar. Unmapped scalars are kept under source_payload.unmapped and
listed in unmapped_source_keys so new provider fields are visible, not lost.

Usage:
    python -m scripts.populate_clean_company_profile
"""

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.crispdm.db import engine

SOURCE_KEY_RENAMES = {"52_week_change": "pct_change_52w"}
# Nested OpenBB arrays -> target child table (None = intentionally ignored).
NESTED_SOURCE_KEYS = {
    "company_officers": "clean.company_officer",
    "corporate_actions": "clean.corporate_action",
    # yfinance's executive_team repeats company_officers with fewer fields.
    "executive_team": None,
}
DATE_EPOCH_FIELDS = {
    "dividend_date",
    "ex_dividend_date",
    "last_dividend_date",
    "date_short_interest",
    "most_recent_quarter",
    "last_fiscal_year_end",
    "next_fiscal_year_end",
    "governance_epoch_date",
}
TIMESTAMP_EPOCH_FIELDS = {
    "pre_market_time",
    "regular_market_time",
    "earnings_timestamp",
    "earnings_timestamp_end",
}
PROFILE_METADATA_COLUMNS = {
    "profile_id",
    "parent_name",
    "reference_security_id",
    "source_profile_security_id",
    "source_provider",
    "source_retrieved_at",
    "c2_c3_leverage_exempt",
    "source_payload",
    "loaded_at",
    "cik",
    "issuer_id",
    "unmapped_source_keys",
    "non_finite_fields",
}
OFFICER_COLUMNS = (
    "profile_id",
    "symbol",
    "parent_name",
    "officer_no",
    "age",
    "name",
    "title",
    "total_pay",
    "year_born",
    "fiscal_year",
    "exercised_value",
    "unexercised_value",
    "officer_max_age",
    "source_payload",
)
CORPORATE_ACTION_COLUMNS = (
    "profile_id",
    "action_no",
    "symbol",
    "security_id",
    "event_type",
    "effective_date",
    "amount",
    "split_ratio",
    "new_ticker",
    "old_name",
    "new_name",
    "header",
    "message",
    "source_retrieved_at",
    "source_payload",
)


class NonFiniteValue(ValueError):
    """A provider numeric was Infinity/-Infinity/NaN."""


def _epoch_seconds(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not an epoch timestamp")
    epoch = Decimal(str(value))
    if not epoch.is_finite():
        raise ValueError(f"invalid epoch timestamp {value!r}")
    if abs(epoch) >= Decimal("100000000000"):
        epoch /= 1000
    return float(epoch)


def _normalize_dividend_yield(raw_yield, dividend_rate, current_price, provider):
    """Normalize a provider yield only when its unit is corroborated.

    OpenBB/YFinance can expose dividend_yield as percent points or as a
    fraction. The annual dividend/current-price pair disambiguates the unit;
    an unsupported or inconsistent value is retained only in source_payload.
    """
    if raw_yield is None:
        return None, None
    if "OPENBB_YFINANCE" not in str(provider or "").upper():
        return None, "unverified"
    try:
        yield_value = Decimal(str(raw_yield))
        annual_rate = Decimal(str(dividend_rate))
        price = Decimal(str(current_price))
    except (InvalidOperation, TypeError, ValueError):
        return None, "unverified"
    if not all(value.is_finite() for value in (yield_value, annual_rate, price)) or price <= 0:
        return None, "unverified"

    expected_fraction = annual_rate / price
    tolerance = max(abs(expected_fraction) * Decimal("0.02"), Decimal("0.0001"))
    fraction_match = abs(yield_value - expected_fraction) <= tolerance
    percent_points_match = abs(yield_value / Decimal(100) - expected_fraction) <= tolerance
    if fraction_match == percent_points_match:
        return None, "ambiguous" if fraction_match else "unverified"
    if percent_points_match:
        return yield_value / Decimal(100), "percent_points"
    return yield_value, "fraction"


def _finite_decimal(value):
    try:
        decimal_value = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value {value!r}") from exc
    if not decimal_value.is_finite():
        raise NonFiniteValue(f"non-finite numeric value {value!r}")
    return decimal_value


def _coerce_profile_value(source_key, target_type, value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    if source_key in DATE_EPOCH_FIELDS:
        if isinstance(value, (int, float, Decimal)):
            return datetime.fromtimestamp(_epoch_seconds(value), timezone.utc).date()
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.date()

    if source_key in TIMESTAMP_EPOCH_FIELDS:
        if isinstance(value, (int, float, Decimal)):
            return datetime.fromtimestamp(_epoch_seconds(value), timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)

    if target_type == "boolean":
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"true", "t", "yes", "1"}:
            return True
        if normalized in {"false", "f", "no", "0"}:
            return False
        raise ValueError(f"cannot parse boolean value {value!r}")

    if target_type == "bigint":
        decimal_value = _finite_decimal(value)
        if decimal_value != decimal_value.to_integral_value():
            raise ValueError(f"non-integral value {value!r} for BIGINT field")
        return int(decimal_value)

    if target_type == "numeric":
        return _finite_decimal(value)

    if target_type in {"text", "character varying"}:
        return str(value)

    raise ValueError(f"unsupported profile column type {target_type!r}")


def _profile_column_types(conn):
    rows = (
        conn.execute(
            text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'clean'
          AND table_name = 'company_profile'
        ORDER BY ordinal_position
    """)
        )
        .mappings()
        .all()
    )
    if not rows:
        raise RuntimeError("clean.company_profile is missing; apply database migrations first")
    return {
        row["column_name"]: row["data_type"]
        for row in rows
        if row["column_name"] not in PROFILE_METADATA_COLUMNS
    }


def _load_source_profiles(conn):
    return (
        conn.execute(
            text("""
        SELECT DISTINCT ON (
                   UPPER(BTRIM(COALESCE(
                       NULLIF(BTRIM(raw_payload #>> '{openbb,symbol}'), ''),
                       NULLIF(BTRIM(raw_payload ->> 'symbol'), ''),
                       tp.ticker
                   ))),
                   BTRIM(COALESCE(
                       NULLIF(BTRIM(raw_payload #>> '{openbb,name}'), ''),
                       NULLIF(BTRIM(raw_payload #>> '{openbb,long_name}'), ''),
                       NULLIF(BTRIM(raw_payload ->> 'name'), ''),
                       NULLIF(BTRIM(raw_payload ->> 'long_name'), '')
                   ))
               )
               tp.security_id,
               tp.ticker,
               tp.provider,
               tp.retrieved_at,
               tp.raw_payload,
               s.cik,
               s.issuer_id
        FROM raw.ticker_profile AS tp
        LEFT JOIN reference.securities AS s ON s.security_id = tp.security_id
        WHERE jsonb_typeof(raw_payload) = 'object'
          AND NULLIF(BTRIM(COALESCE(
              NULLIF(BTRIM(raw_payload #>> '{openbb,symbol}'), ''),
              NULLIF(BTRIM(raw_payload ->> 'symbol'), ''),
              tp.ticker
          )), '') IS NOT NULL
          AND COALESCE(
              NULLIF(BTRIM(raw_payload #>> '{openbb,name}'), ''),
              NULLIF(BTRIM(raw_payload #>> '{openbb,long_name}'), ''),
              NULLIF(BTRIM(raw_payload ->> 'name'), ''),
              NULLIF(BTRIM(raw_payload ->> 'long_name'), '')
          ) IS NOT NULL
        ORDER BY UPPER(BTRIM(COALESCE(
                     NULLIF(BTRIM(raw_payload #>> '{openbb,symbol}'), ''),
                     NULLIF(BTRIM(raw_payload ->> 'symbol'), ''),
                     tp.ticker
                 ))),
                 BTRIM(COALESCE(
                     NULLIF(BTRIM(raw_payload #>> '{openbb,name}'), ''),
                     NULLIF(BTRIM(raw_payload #>> '{openbb,long_name}'), ''),
                     NULLIF(BTRIM(raw_payload ->> 'name'), ''),
                     NULLIF(BTRIM(raw_payload ->> 'long_name'), '')
                 )),
                 CASE
                     WHEN tp.provider = 'SEC_XBRL+OPENBB_YFINANCE' THEN 2
                     WHEN tp.provider = 'OPENBB_YFINANCE' THEN 1
                     ELSE 0
                 END DESC,
                 tp.retrieved_at DESC NULLS LAST,
                 tp.security_id
    """)
        )
        .mappings()
        .all()
    )


def _nested_array(source_payload, openbb_payload, key):
    value = openbb_payload.get(key)
    if value is None and openbb_payload is not source_payload:
        value = source_payload.get(key)
    return value or []


def _clean_profile_row(source, column_types):
    source_payload = source["raw_payload"]
    openbb_payload = source_payload.get("openbb")
    if not isinstance(openbb_payload, dict):
        openbb_payload = source_payload

    def _first_text(*candidates):
        for candidate in candidates:
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        return ""

    # The OpenBB profile is authoritative for identity; top-level keys are only
    # read for legacy flat payloads.
    symbol = _first_text(
        openbb_payload.get("symbol"), source_payload.get("symbol"), source["ticker"]
    ).upper()
    parent_name = _first_text(
        openbb_payload.get("name"),
        openbb_payload.get("long_name"),
        source_payload.get("name"),
        source_payload.get("long_name"),
    )
    if not symbol or not parent_name:
        raise ValueError("company profile source is missing symbol or parent name")

    values = {column: None for column in column_types}
    values.update(
        {
            "symbol": symbol,
            "parent_name": parent_name,
            "reference_security_id": source["security_id"],
            "source_profile_security_id": source["security_id"],
            "source_provider": source["provider"],
            "source_retrieved_at": source["retrieved_at"],
            "cik": source.get("cik"),
            "issuer_id": source.get("issuer_id"),
        }
    )
    mapped_scalars = {}
    unmapped_scalars = {}
    non_finite_fields = []
    for source_key, raw_value in openbb_payload.items():
        if source_key in NESTED_SOURCE_KEYS or (
            openbb_payload is source_payload and source_key in ("sec_xbrl", "sec_xbrl_scope")
        ):
            continue
        target_key = SOURCE_KEY_RENAMES.get(source_key, source_key)
        if target_key not in column_types or isinstance(raw_value, (dict, list)):
            unmapped_scalars[source_key] = raw_value
            continue
        mapped_scalars[source_key] = raw_value
        try:
            values[target_key] = _coerce_profile_value(
                source_key, column_types[target_key], raw_value
            )
        except NonFiniteValue:
            values[target_key] = None
            non_finite_fields.append(target_key)

    values["dividend_yield_fraction"], values["dividend_yield_source_unit"] = (
        _normalize_dividend_yield(
            values.get("dividend_yield"),
            values.get("dividend_rate"),
            values.get("current_price"),
            source["provider"],
        )
    )

    values["symbol"] = symbol
    values["non_finite_fields"] = sorted(non_finite_fields)
    values["unmapped_source_keys"] = sorted(unmapped_scalars)
    if openbb_payload is source_payload:
        clean_source_payload = dict(mapped_scalars)
        for key in ("sec_xbrl", "sec_xbrl_scope"):
            if key in source_payload:
                clean_source_payload[key] = source_payload[key]
    else:
        clean_source_payload = {
            **{
                key: value
                for key, value in source_payload.items()
                if key != "openbb" and key not in NESTED_SOURCE_KEYS
            },
            "openbb": mapped_scalars,
        }
    if unmapped_scalars:
        clean_source_payload["unmapped"] = unmapped_scalars
    values["source_payload"] = json.dumps(clean_source_payload, default=str)
    officers = _nested_array(source_payload, openbb_payload, "company_officers")
    return values, officers


def _clean_corporate_action_rows(source, symbol):
    source_payload = source["raw_payload"]
    openbb_payload = source_payload.get("openbb")
    if not isinstance(openbb_payload, dict):
        openbb_payload = source_payload
    actions = _nested_array(source_payload, openbb_payload, "corporate_actions")
    if not isinstance(actions, list):
        raise ValueError(f"corporate_actions must be an array for {symbol}")

    rows = []
    for ordinal, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ValueError(f"corporate action {ordinal} is not an object for {symbol}")
        meta = action.get("meta") if isinstance(action.get("meta"), dict) else {}
        event_type = str(meta.get("eventType") or "").strip().upper()
        if not event_type:
            raise ValueError(f"corporate action {ordinal} has no eventType for {symbol}")
        epoch_ms = meta.get("dateEpochMs")
        effective_date = None
        if epoch_ms not in (None, ""):
            effective_date = datetime.fromtimestamp(
                float(Decimal(str(epoch_ms)) / 1000), timezone.utc
            ).date()
        amount = meta.get("amount")
        try:
            amount = _finite_decimal(amount) if amount not in (None, "") else None
        except ValueError:
            amount = None
        rows.append(
            {
                "profile_id": None,
                "action_no": ordinal,
                "symbol": symbol,
                "security_id": source["security_id"],
                "event_type": event_type,
                "effective_date": effective_date,
                "amount": amount,
                "split_ratio": meta.get("splitRatio"),
                "new_ticker": meta.get("newTicker"),
                "old_name": meta.get("oldName"),
                "new_name": meta.get("newName"),
                "header": action.get("header"),
                "message": action.get("message"),
                "source_retrieved_at": source["retrieved_at"],
                "source_payload": json.dumps(action, default=str),
            }
        )
    return rows


def _clean_officer_rows(symbol, parent_name, officers):
    if not isinstance(officers, list):
        raise ValueError(f"company_officers must be an array for {symbol}/{parent_name}")

    rows = []
    for ordinal, officer in enumerate(officers, start=1):
        if not isinstance(officer, dict):
            raise ValueError(f"officer row {ordinal} is not an object for {symbol}")
        officer_name = officer.get("name")
        if not officer_name:
            raise ValueError(f"officer row {ordinal} has no name for {symbol}")
        rows.append(
            {
                "profile_id": None,
                "symbol": symbol,
                "parent_name": parent_name,
                "officer_no": ordinal,
                "age": officer.get("age"),
                "name": str(officer_name).strip(),
                "title": officer.get("title"),
                "total_pay": officer.get("totalPay"),
                "year_born": officer.get("yearBorn"),
                "fiscal_year": officer.get("fiscalYear"),
                "exercised_value": officer.get("exercisedValue"),
                "unexercised_value": officer.get("unexercisedValue"),
                "officer_max_age": officer.get("officer_max_age"),
                "source_payload": json.dumps(officer, default=str),
            }
        )
    return rows


def _insert_statement(conn, table, columns):
    preparer = conn.dialect.identifier_preparer
    quoted_columns = [preparer.quote(column) for column in columns]
    binds = [f":{column}" for column in columns]
    return text(f"INSERT INTO {table} ({', '.join(quoted_columns)}) VALUES ({', '.join(binds)})")


def rebuild_company_profiles():
    """Atomically rebuild company profiles and their officer/corporate-action rows."""
    with engine.begin() as conn:
        column_types = _profile_column_types(conn)
        sources = _load_source_profiles(conn)
        if not sources:
            raise RuntimeError("no company-profile payloads found in raw.ticker_profile")

        profile_columns = [
            "parent_name",
            "reference_security_id",
            "source_profile_security_id",
            "source_provider",
            "source_retrieved_at",
            "cik",
            "issuer_id",
            *column_types,
            "unmapped_source_keys",
            "non_finite_fields",
            "source_payload",
        ]
        profile_rows = []
        officer_rows = []
        action_rows = []
        unmapped_keys = set()
        for source in sources:
            row, officers = _clean_profile_row(source, column_types)
            profile_rows.append(row)
            unmapped_keys.update(row["unmapped_source_keys"])
            officer_rows.extend(_clean_officer_rows(row["symbol"], row["parent_name"], officers))
            action_rows.extend(
                (row["parent_name"], action)
                for action in _clean_corporate_action_rows(source, row["symbol"])
            )

        conn.execute(text("DELETE FROM clean.company_profile"))
        conn.execute(
            _insert_statement(conn, "clean.company_profile", profile_columns),
            profile_rows,
        )
        profile_ids = {
            (item["symbol"], item["parent_name"]): item["profile_id"]
            for item in conn.execute(
                text("SELECT profile_id, symbol, parent_name FROM clean.company_profile")
            )
            .mappings()
            .all()
        }
        for officer in officer_rows:
            officer["profile_id"] = profile_ids[(officer["symbol"], officer["parent_name"])]
        actions = []
        for parent_name, action in action_rows:
            action["profile_id"] = profile_ids[(action["symbol"], parent_name)]
            actions.append(action)

        if officer_rows:
            conn.execute(
                _insert_statement(conn, "clean.company_officer", OFFICER_COLUMNS),
                officer_rows,
            )
        if actions:
            conn.execute(
                _insert_statement(conn, "clean.corporate_action", CORPORATE_ACTION_COLUMNS),
                actions,
            )
    return {
        "profiles": len(profile_rows),
        "officers": len(officer_rows),
        "corporate_actions": len(actions),
        "non_finite_profiles": sum(1 for row in profile_rows if row["non_finite_fields"]),
        "unmapped_source_keys": sorted(unmapped_keys),
    }


def main():
    summary = rebuild_company_profiles()
    print(
        "Rebuilt clean company profiles: "
        f"{summary['profiles']} profiles, {summary['officers']} officers, "
        f"{summary['corporate_actions']} corporate actions"
    )
    if summary["non_finite_profiles"]:
        print(
            f"  profiles with non-finite numerics loaded as NULL: {summary['non_finite_profiles']}"
        )
    if summary["unmapped_source_keys"]:
        keys = summary["unmapped_source_keys"]
        print(f"  unmapped OpenBB scalar keys ({len(keys)}), kept in source_payload.unmapped:")
        print("    " + ", ".join(keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())
