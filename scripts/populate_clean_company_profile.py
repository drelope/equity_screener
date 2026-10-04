"""Build clean company-profile and officer tables from raw OpenBB profiles.

Company scalars are stored in clean.company_profile; each company_officers
entry is stored as a child row. The 52_week_change source key is mapped to
pct_change_52w, epoch fields are converted to UTC dates/timestamps, and
missing compensation remains NULL.

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
DATE_EPOCH_FIELDS = {
    "dividend_date",
    "ex_dividend_date",
    "last_dividend_date",
    "date_short_interest",
    "most_recent_quarter",
    "last_fiscal_year_end",
    "next_fiscal_year_end",
    "governance_epoch_date",
    "earnings_timestamp",
}
TIMESTAMP_EPOCH_FIELDS = {
    "pre_market_time",
    "regular_market_time",
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
}


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
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.to_integral_value():
            raise ValueError(f"non-integral value {value!r} for BIGINT field")
        return int(decimal_value)

    if target_type == "numeric":
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"invalid numeric value {value!r}") from exc

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
                       raw_payload #>> '{openbb,symbol}',
                       raw_payload ->> 'symbol',
                       ticker
                   ))),
                   BTRIM(COALESCE(
                       NULLIF(raw_payload #>> '{openbb,name}', ''),
                       NULLIF(raw_payload #>> '{openbb,long_name}', ''),
                       NULLIF(raw_payload ->> 'name', ''),
                       NULLIF(raw_payload ->> 'long_name', '')
                   ))
               )
               security_id,
               ticker,
               provider,
               retrieved_at,
               raw_payload
        FROM raw.ticker_profile
        WHERE jsonb_typeof(raw_payload) = 'object'
          AND NULLIF(BTRIM(COALESCE(
              raw_payload #>> '{openbb,symbol}', raw_payload ->> 'symbol', ticker
          )), '') IS NOT NULL
          AND NULLIF(BTRIM(COALESCE(
              raw_payload #>> '{openbb,name}',
              raw_payload #>> '{openbb,long_name}',
              raw_payload ->> 'name',
              raw_payload ->> 'long_name'
          )), '') IS NOT NULL
        ORDER BY UPPER(BTRIM(COALESCE(
                     raw_payload #>> '{openbb,symbol}', raw_payload ->> 'symbol', ticker
                 ))),
                 BTRIM(COALESCE(
                     NULLIF(raw_payload #>> '{openbb,name}', ''),
                     NULLIF(raw_payload #>> '{openbb,long_name}', ''),
                     NULLIF(raw_payload ->> 'name', ''),
                     NULLIF(raw_payload ->> 'long_name', '')
                 )),
                 CASE
                     WHEN provider = 'SEC_XBRL+OPENBB_YFINANCE' THEN 2
                     WHEN provider = 'OPENBB_YFINANCE' THEN 1
                     ELSE 0
                 END DESC,
                 retrieved_at DESC NULLS LAST,
                 security_id
    """)
        )
        .mappings()
        .all()
    )


def _clean_profile_row(source, column_types):
    source_payload = source["raw_payload"]
    openbb_payload = source_payload.get("openbb")
    if not isinstance(openbb_payload, dict):
        openbb_payload = source_payload
    source_symbol = source_payload.get("symbol") or openbb_payload.get("symbol") or source["ticker"]
    symbol = str(source_symbol).strip().upper()
    parent_name = str(
        source_payload.get("name")
        or source_payload.get("long_name")
        or openbb_payload.get("name")
        or openbb_payload.get("long_name")
        or ""
    ).strip()
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
        }
    )
    preserved_scalars = {}
    for source_key, raw_value in openbb_payload.items():
        target_key = SOURCE_KEY_RENAMES.get(source_key, source_key)
        if target_key not in column_types or isinstance(raw_value, (dict, list)):
            continue
        value = _coerce_profile_value(source_key, column_types[target_key], raw_value)
        values[target_key] = value
        preserved_scalars[source_key] = raw_value

    values["dividend_yield_fraction"], values["dividend_yield_source_unit"] = (
        _normalize_dividend_yield(
            values.get("dividend_yield"),
            values.get("dividend_rate"),
            values.get("current_price"),
            source["provider"],
        )
    )

    values["symbol"] = symbol
    if openbb_payload is source_payload:
        clean_source_payload = preserved_scalars
    else:
        clean_source_payload = {
            **{
                key: value
                for key, value in source_payload.items()
                if key not in {"openbb", "company_officers"}
            },
            "openbb": preserved_scalars,
        }
    values["source_payload"] = json.dumps(clean_source_payload, default=str)
    officers = (
        source_payload.get("company_officers") or openbb_payload.get("company_officers") or []
    )
    return values, officers


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
    """Atomically rebuild company profiles and their normalized officer rows."""
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
            *column_types,
            "source_payload",
        ]
        profile_rows = []
        officer_rows = []
        for source in sources:
            row, officers = _clean_profile_row(source, column_types)
            profile_rows.append(row)
            officer_rows.extend(_clean_officer_rows(row["symbol"], row["parent_name"], officers))

        conn.execute(text("DELETE FROM clean.company_profile"))
        conn.execute(
            _insert_statement(conn, "clean.company_profile", profile_columns),
            profile_rows,
        )
        if officer_rows:
            conn.execute(
                _insert_statement(
                    conn,
                    "clean.company_officer",
                    [
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
                    ],
                ),
                officer_rows,
            )
    return len(profile_rows), len(officer_rows)


def main():
    profiles, officers = rebuild_company_profiles()
    print(f"Rebuilt clean company profiles: {profiles} profiles, {officers} officers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
