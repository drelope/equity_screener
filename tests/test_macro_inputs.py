from datetime import date

import pandas as pd

from src.crispdm import macro_inputs as mi


def _hit(value, as_of=date(2026, 10, 20), unit="percent", source="FMP"):
    return {"value": value, "as_of": as_of, "unit": unit, "source": source, "provider": "x"}


def test_treasury_melt_converts_decimals_to_percent_and_skips_missing():
    frame = pd.DataFrame(
        {"month_2": [0.0417], "year_10": [float("nan")], "year_30": [0.0548]},
        index=pd.Index([date(2026, 10, 20)], name="date"),
    )

    rows = mi.rows_from_treasury(frame)

    assert {row["series_id"] for row in rows} == {"UST_2M", "UST_30Y"}
    by_id = {row["series_id"]: row for row in rows}
    assert by_id["UST_2M"]["value"] == 4.17
    assert by_id["UST_2M"]["unit"] == "percent"
    assert by_id["UST_2M"]["source"] == "FMP"
    assert by_id["UST_2M"]["provider"] == "fixedincome.government.treasury_rates"
    assert by_id["UST_2M"]["observation_date"] == date(2026, 10, 20)


def test_history_melt_maps_provider_symbols_to_series_ids():
    frame = pd.DataFrame(
        {"symbol": ["XAUUSD", "XAUUSD", "NOSUCH"], "close": [4125.5, float("nan"), 1.0]},
        index=pd.Index([date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 20)], name="date"),
    )

    rows = mi.rows_from_history(frame, "FMP", "equity")

    assert [(row["series_id"], row["value"]) for row in rows] == [("GOLD_SPOT", 4125.5)]
    assert rows[0]["unit"] == "USD/oz"


def test_fred_melt_keeps_non_nan_observations_with_series_units():
    frame = pd.DataFrame(
        {"SOFR": [3.89, float("nan")], "RRPONTSYD": [320.5, 319.0]},
        index=pd.Index([date(2026, 10, 19), date(2026, 10, 20)], name="date"),
    )

    rows = mi.rows_from_fred(frame)

    by_key = {(row["series_id"], row["observation_date"]): row["value"] for row in rows}
    assert by_key[("SOFR", date(2026, 10, 19))] == 3.89
    assert ("SOFR", date(2026, 10, 20)) not in by_key
    assert by_key[("RRP", date(2026, 10, 20))] == 319.0
    rrp = next(row for row in rows if row["series_id"] == "RRP")
    assert rrp["unit"] == "billions USD"
    assert all(row["source"] == "FRED" for row in rows)


def test_risk_premium_takes_the_united_states_total_row():
    frame = pd.DataFrame(
        {"country": ["Canada", "United States"], "total_equity_risk_premium": [6.1, 4.46]}
    )

    rows = mi.rows_from_risk_premium(frame, date(2026, 10, 20))

    assert len(rows) == 1
    assert rows[0]["series_id"] == "ERP_US"
    assert rows[0]["value"] == 4.46
    assert rows[0]["observation_date"] == date(2026, 10, 20)


def test_latest_from_rows_keeps_the_newest_observation_regardless_of_order():
    older = {
        "series_id": "VIX",
        "observation_date": "2026-10-19",
        "value": 18.4,
        "unit": "index points",
        "source": "FMP",
    }
    newer = {**older, "observation_date": "2026-10-20", "value": 17.31}

    latest = mi.latest_from_rows([newer, older])

    assert latest["VIX"]["value"] == 17.31
    assert latest["VIX"]["as_of"] == date(2026, 10, 20)


def test_build_inputs_marks_stored_series_observed_and_gaps_unverified():
    latest = {"UST_2Y": _hit(4.79)}

    entries = {entry["id"]: entry for entry in mi.build_inputs(latest)}

    assert entries["UST_2Y"]["status"] == "Observed"
    assert entries["UST_2Y"]["value"] == 4.79
    assert entries["UST_10Y"]["status"] == "UNVERIFIED"
    assert "populate_macro_inputs" in entries["UST_10Y"]["reason"]
    assert entries["MOVE"]["status"] == "UNVERIFIED"
    assert "402" in entries["MOVE"]["reason"]


def test_derived_inputs_compute_from_stored_values():
    latest = {
        "UST_10Y": _hit(5.12),
        "UST_2Y": _hit(4.79),
        "UST_3M": _hit(4.26),
        "GOLD_SPOT": _hit(4125.465, unit="USD/oz"),
        "SILVER_SPOT": _hit(57.816, unit="USD/oz"),
    }

    entries = {entry["id"]: entry for entry in mi.build_inputs(latest)}

    assert entries["2s10s"]["status"] == "Observed"
    assert abs(entries["2s10s"]["value"] - 33.0) < 1e-9
    assert entries["2s10s"]["source"] == "derived"
    assert abs(entries["3m10y"]["value"] - 86.0) < 1e-9
    assert abs(entries["GOLD_SILVER_RATIO"]["value"] - 71.355) < 1e-3


def test_derived_inputs_stay_unverified_when_an_input_is_missing():
    entries = {entry["id"]: entry for entry in mi.build_inputs({"UST_10Y": _hit(5.12)})}

    assert entries["2s10s"]["status"] == "UNVERIFIED"
    assert "inputs missing" in entries["2s10s"]["reason"]


def test_build_inputs_covers_every_memo_token_in_its_group():
    entries = {entry["id"]: entry for entry in mi.build_inputs({})}

    for group in mi.GROUPS:
        for series_id in mi.DOC_ORDER[group]:
            assert series_id in entries
            assert entries[series_id]["group"] == group
    assert all(entry["status"] in {"Observed", "UNVERIFIED"} for entry in entries.values())


def test_registry_routes_resolve_for_every_spec():
    for spec in mi.SPECS:
        assert spec.route in mi.PROVIDER_ROUTES
        if spec.fred_id:
            assert spec.source == "FRED"
            assert spec.fred_id in mi.FRED_IDS
        else:
            assert spec.source == "FMP"
    for series_id in mi.TENOR_SERIES:
        assert series_id in mi.SPECS_BY_ID


def test_render_markdown_follows_memo_line_order_and_labels():
    entries = mi.build_inputs({"UST_2Y": _hit(4.79), "VIX": _hit(17.31, unit="index points")})

    text = mi.render_markdown(entries, "2026-10-20", {"PFF": 0.47})

    titles = ("Curve / rates", "Funding / front end", "Credit", "Commodities", "Risk", "Benchmarks")
    positions = [text.index(title) for title in titles]
    assert positions == sorted(positions)
    assert "**as_of**: `2026-10-20`" in text
    assert "`UST_2Y` 4.79% **Observed** (FMP, 2026-10-20)" in text
    assert "`VIX` 17.31 **Observed** (FMP, 2026-10-20)" in text
    assert "`MOVE` **UNVERIFIED**" in text
    assert "PFF financials 47.0% **Observed**" in text
    assert "duration and call exposure **UNVERIFIED**" in text


def test_format_value_renders_each_unit():
    assert mi.format_value(4.79, "percent") == "4.79%"
    assert mi.format_value(32.7, "bp") == "+33bp"
    assert mi.format_value(4125.465, "USD/oz") == "$4,125.47"
    assert mi.format_value(17.31, "index points") == "17.31"
    assert mi.format_value(320.5, "billions USD") == "$320.5B"
    assert mi.format_value(0.227, "billions USD") == "$0.23B"
    assert mi.format_value(None, "percent") is None


def test_financials_weight_sums_only_financial_sectors():
    rows = [
        {"symbol": "PFF", "sector": "Financial Services", "value": 0.47},
        {"symbol": "PFF", "sector": "Real Estate", "value": 0.10},
        {"symbol": "SDY", "sector": "Financial Services", "value": 0.14},
    ]

    assert mi.financials_weight(rows) == {"PFF": 0.47, "SDY": 0.14}


def test_collect_rows_skips_fmp_series_when_the_key_is_missing(monkeypatch):
    from src.crispdm import openbb_client

    monkeypatch.setattr(openbb_client, "_has_fmp_key", lambda: False)
    monkeypatch.setattr(openbb_client, "_has_fred_key", lambda: True)
    monkeypatch.setattr(
        openbb_client,
        "macro_fred",
        lambda ids, start_date=None, end_date=None: pd.DataFrame(
            {"SOFR": [3.9]}, index=pd.Index([date(2026, 10, 20)], name="date")
        ),
    )

    rows, sectors, stats = mi.collect_rows()

    assert sectors == []
    assert {row["series_id"] for row in rows} == {"SOFR"}
    assert stats["attempted"] == len(mi.FRED_IDS)
    assert stats["skipped"] == len([spec for spec in mi.SPECS if spec.source == "FMP"])
    assert stats["errors"] == 0


def test_collect_rows_without_any_key_skips_everything_cleanly(monkeypatch):
    from src.crispdm import openbb_client

    monkeypatch.setattr(openbb_client, "_has_fmp_key", lambda: False)
    monkeypatch.setattr(openbb_client, "_has_fred_key", lambda: False)

    rows, sectors, stats = mi.collect_rows(include_sectors=True)

    assert rows == [] and sectors == []
    assert stats["attempted"] == 0
    assert stats["skipped"] == len(mi.SPECS) + len(mi.SECTOR_SYMBOLS)
    assert stats["errors"] == 0
