"""Series registry for docs/GlobalMacroStrategy.md economic inputs.

Single source of truth for the macro economic inputs the strategy memo's
Inputs block needs: which series exist (``raw.macro_series`` keys, units,
provider), which memo inputs have no provider behind them (UNVERIFIED with a
stated reason), how derived inputs (2s10s, 3m10y, gold/silver ratio) are
computed, and how the whole set renders back into the memo's Inputs bullets.

Group names and per-group order follow the memo's Inputs lines exactly,
including breakevens and TIPS real yields sitting under Commodities.

Supporting data only: nothing here feeds the model feature build.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

GROUPS = ("curve", "funding", "credit", "commodities", "risk", "benchmarks")

GROUP_TITLES = {
    "curve": "Curve / rates",
    "funding": "Funding / front end",
    "credit": "Credit",
    "commodities": "Commodities",
    "risk": "Risk",
    "benchmarks": "Benchmarks",
}

LOOKBACK_DAYS_DEFAULT = 60

PROVIDER_ROUTES = {
    "treasury": "fixedincome.government.treasury_rates",
    "equity": "equity.price.historical",
    "etf": "etf.historical",
    "risk_premium": "economy.risk_premium",
    "fred": "economy.fred_series",
    "sectors": "etf.sectors",
}

#: FMP treasury frame column -> stored series id; values are decimals (0.0512)
#: and are stored as percent (5.12).
TENOR_COLUMNS = {
    "month_1": "UST_1M",
    "month_2": "UST_2M",
    "month_3": "UST_3M",
    "month_6": "UST_6M",
    "year_1": "UST_1Y",
    "year_2": "UST_2Y",
    "year_3": "UST_3Y",
    "year_5": "UST_5Y",
    "year_7": "UST_7Y",
    "year_10": "UST_10Y",
    "year_20": "UST_20Y",
    "year_30": "UST_30Y",
}

TENOR_SERIES = frozenset(TENOR_COLUMNS.values())

SECTOR_SYMBOLS = ("PFF", "PGX", "SDY")


@dataclass(frozen=True)
class SeriesSpec:
    """One stored series in raw.macro_series."""

    series_id: str
    label: str
    unit: str
    group: str
    symbol: str = ""
    fred_id: str = ""
    fetch: str = "equity"
    doc_input: bool = True
    note: str = ""

    @property
    def source(self) -> str:
        return "FRED" if self.fred_id else "FMP"

    @property
    def route(self) -> str:
        if self.fred_id:
            return "fred"
        if self.series_id in TENOR_SERIES:
            return "treasury"
        if self.series_id == "ERP_US":
            return "risk_premium"
        return self.fetch


@dataclass(frozen=True)
class DerivedSpec:
    """A memo input computed from other stored series at read time."""

    series_id: str
    label: str
    unit: str
    group: str
    formula: str
    inputs: tuple[str, ...]
    compute: Callable[[Mapping[str, float]], float]
    doc_input: bool = True
    note: str = ""


@dataclass(frozen=True)
class UnavailableEntry:
    """A memo input neither FMP nor FRED carries: always UNVERIFIED."""

    series_id: str
    label: str
    group: str
    reason: str


SPECS: tuple[SeriesSpec, ...] = (
    # Curve / rates (FMP treasury frame, one call yields the whole curve)
    SeriesSpec("UST_1M", "UST_1M", "percent", "curve"),
    SeriesSpec("UST_2M", "UST_2M", "percent", "curve"),
    SeriesSpec("UST_3M", "UST_3M", "percent", "curve"),
    SeriesSpec("UST_6M", "UST_6M", "percent", "curve"),
    SeriesSpec("UST_1Y", "UST_1Y", "percent", "curve"),
    SeriesSpec("UST_2Y", "UST_2Y", "percent", "curve"),
    SeriesSpec("UST_3Y", "UST_3Y", "percent", "curve"),
    SeriesSpec("UST_5Y", "UST_5Y", "percent", "curve"),
    SeriesSpec("UST_7Y", "UST_7Y", "percent", "curve"),
    SeriesSpec("UST_10Y", "UST_10Y", "percent", "curve"),
    SeriesSpec("UST_20Y", "UST_20Y", "percent", "curve"),
    SeriesSpec("UST_30Y", "UST_30Y", "percent", "curve"),
    # Funding / front end (FRED)
    SeriesSpec(
        "SOFR",
        "SOFR (o/n)",
        "percent",
        "funding",
        fred_id="SOFR",
    ),
    SeriesSpec(
        "SOFR_90D",
        "Term SOFR 3M",
        "percent",
        "funding",
        fred_id="SOFR90DAYAVG",
        note="90-day average SOFR from FRED; CME Term SOFR is not carried by FMP or FRED",
    ),
    SeriesSpec(
        "RRP",
        "RRP balance",
        "billions USD",
        "funding",
        fred_id="RRPONTSYD",
    ),
    # Credit (FRED ICE BofA OAS)
    SeriesSpec("IG_OAS", "IG OAS", "percent", "credit", fred_id="BAMLC0A0CM"),
    SeriesSpec("HY_OAS", "HY OAS", "percent", "credit", fred_id="BAMLH0A0HYM2"),
    # Commodities (FRED daily spot, FMP metals, ETF proxies)
    SeriesSpec("WTI", "WTI (spot)", "USD/bbl", "commodities", fred_id="DCOILWTICO"),
    SeriesSpec("BRENT", "Brent (spot)", "USD/bbl", "commodities", fred_id="DCOILBRENTEU"),
    SeriesSpec(
        "HENRY_HUB",
        "Henry Hub",
        "USD/MMBtu",
        "commodities",
        fred_id="DHHNGSP",
    ),
    SeriesSpec("GOLD_SPOT", "Gold", "USD/oz", "commodities", symbol="XAUUSD"),
    SeriesSpec("SILVER_SPOT", "Silver", "USD/oz", "commodities", symbol="XAGUSD"),
    SeriesSpec(
        "COPPER",
        "Copper",
        "USD",
        "commodities",
        symbol="CPER",
        fetch="etf",
        note="CPER ETF close proxy; neither provider carries a spot copper price",
    ),
    SeriesSpec(
        "CRB_BCOM",
        "CRB/BCOM",
        "USD",
        "commodities",
        symbol="DBC",
        fetch="etf",
        note="DBC ETF close proxy for the CRB/BCOM indices",
    ),
    SeriesSpec("BE_5Y", "5y breakeven", "percent", "commodities", fred_id="T5YIE", doc_input=False),
    SeriesSpec(
        "BE_10Y",
        "10y breakeven",
        "percent",
        "commodities",
        fred_id="T10YIE",
        doc_input=False,
    ),
    SeriesSpec(
        "BE_5Y5Y",
        "5y5y breakeven",
        "percent",
        "commodities",
        fred_id="T5YIFR",
        note="FRED 5-year forward inflation expectation rate",
    ),
    SeriesSpec("TIPS_5Y", "5y TIPS real yield", "percent", "commodities", fred_id="DFII5"),
    SeriesSpec("TIPS_10Y", "10y TIPS real yield", "percent", "commodities", fred_id="DFII10"),
    # Risk (FMP)
    SeriesSpec("VIX", "VIX", "index points", "risk", symbol="^VIX"),
    SeriesSpec(
        "ERP_US",
        "US total equity risk premium",
        "percent",
        "risk",
        doc_input=False,
        note="FMP country risk premium for the United States; reference for the "
        "CAPM / implied-ERP discussion, not a memo Inputs token",
    ),
    # Benchmarks (FMP ETF closes)
    SeriesSpec("PFF", "PFF", "USD", "benchmarks", symbol="PFF", fetch="etf"),
    SeriesSpec("PGX", "PGX", "USD", "benchmarks", symbol="PGX", fetch="etf"),
    SeriesSpec("SDY", "SDY", "USD", "benchmarks", symbol="SDY", fetch="etf"),
)

SPECS_BY_ID = {spec.series_id: spec for spec in SPECS}
FRED_BY_ID = {spec.fred_id: spec for spec in SPECS if spec.fred_id}
SYMBOL_SPECS = tuple(spec for spec in SPECS if spec.symbol)
SYMBOLS_BY_SYMBOL = {spec.symbol: spec for spec in SYMBOL_SPECS}

EQUITY_SYMBOLS = tuple(spec.symbol for spec in SYMBOL_SPECS if spec.route == "equity")
ETF_SYMBOLS = tuple(spec.symbol for spec in SYMBOL_SPECS if spec.route == "etf")
FRED_IDS = tuple(spec.fred_id for spec in SPECS if spec.route == "fred")

DERIVED: tuple[DerivedSpec, ...] = (
    DerivedSpec(
        "2s10s",
        "2s10s",
        "bp",
        "curve",
        "10y − 2y, in basis points",
        ("UST_10Y", "UST_2Y"),
        lambda values: (values["UST_10Y"] - values["UST_2Y"]) * 100,
    ),
    DerivedSpec(
        "3m10y",
        "3m10y",
        "bp",
        "curve",
        "10y − 3m, in basis points",
        ("UST_10Y", "UST_3M"),
        lambda values: (values["UST_10Y"] - values["UST_3M"]) * 100,
    ),
    DerivedSpec(
        "GOLD_SILVER_RATIO",
        "Gold/Silver ratio",
        "ratio",
        "commodities",
        "gold price ÷ silver price",
        ("GOLD_SPOT", "SILVER_SPOT"),
        lambda values: values["GOLD_SPOT"] / values["SILVER_SPOT"],
        note="observed spot ratio; the memo uses it as a risk-appetite gauge",
    ),
    DerivedSpec(
        "REAL_10Y",
        "10y real (nominal − BE)",
        "percent",
        "commodities",
        "UST_10Y − 10y breakeven, Fisher cross-check against TIPS_10Y",
        ("UST_10Y", "BE_10Y"),
        lambda values: values["UST_10Y"] - values["BE_10Y"],
        doc_input=False,
    ),
)

DERIVED_BY_ID = {entry.series_id: entry for entry in DERIVED}

UNAVAILABLE: tuple[UnavailableEntry, ...] = (
    UnavailableEntry(
        "TERM_PREMIUM",
        "term-premium estimate",
        "curve",
        "neither FMP nor FRED carries a term-premium series; state the assumed level",
    ),
    UnavailableEntry(
        "REPO_SPIKE_FLAGS",
        "repo-spike flags",
        "funding",
        "no repo-spike flag series on FMP or FRED; SOFR levels alone do not flag spikes",
    ),
    UnavailableEntry(
        "AT1_COCO",
        "bank AT1 / CoCo spread proxy",
        "credit",
        "no AT1/CoCo index from either provider; PFF/PGX are only a weak stand-in",
    ),
    UnavailableEntry(
        "INDUSTRIAL_PREFERRED",
        "industrial preferred spread",
        "credit",
        "no liquid preferred-spread index from either provider; PFF/PGX are financials-heavy",
    ),
    UnavailableEntry(
        "TTF",
        "TTF",
        "commodities",
        "Dutch TTF gas is not carried by FMP or FRED (Henry Hub is observed instead)",
    ),
    UnavailableEntry(
        "MOVE",
        "MOVE",
        "risk",
        "MOVE is a premium index symbol on FMP (HTTP 402) and is not a FRED series",
    ),
)

UNAVAILABLE_BY_ID = {entry.series_id: entry for entry in UNAVAILABLE}

#: Memo Inputs order per group; ids name a spec, a derived entry or an
#: UNAVAILABLE entry. Stored series with ``doc_input=False`` and the derived
#: REAL_10Y are appended after these within their group.
DOC_ORDER: dict[str, tuple[str, ...]] = {
    "curve": ("UST_2Y", "UST_10Y", "UST_30Y", "2s10s", "3m10y", "TERM_PREMIUM"),
    "funding": ("SOFR", "SOFR_90D", "RRP", "REPO_SPIKE_FLAGS"),
    "credit": ("IG_OAS", "HY_OAS", "AT1_COCO", "INDUSTRIAL_PREFERRED"),
    "commodities": (
        "WTI",
        "BRENT",
        "HENRY_HUB",
        "TTF",
        "GOLD_SPOT",
        "SILVER_SPOT",
        "COPPER",
        "CRB_BCOM",
        "GOLD_SILVER_RATIO",
        "BE_5Y5Y",
        "TIPS_5Y",
        "TIPS_10Y",
    ),
    "risk": ("MOVE", "VIX"),
    "benchmarks": ("PFF", "PGX", "SDY"),
}


# --- Frame -> rows ---------------------------------------------------------------


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    return pd.Timestamp(value).date()


def rows_from_treasury(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Melt FMP's decimal treasury frame into stored rows (percent)."""
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for observation, values in frame.iterrows():
        observation_date = _as_date(observation)
        for column, series_id in TENOR_COLUMNS.items():
            value = values.get(column)
            if value is None or pd.isna(value):
                continue
            rows.append(
                {
                    "series_id": series_id,
                    "observation_date": observation_date,
                    "value": round(float(value) * 100, 4),
                    "unit": "percent",
                    "source": "FMP",
                    "provider": PROVIDER_ROUTES["treasury"],
                }
            )
    return rows


def rows_from_history(frame: pd.DataFrame, source: str, route: str) -> list[dict[str, Any]]:
    """Melt an OpenBB history frame (symbol + close) into stored rows."""
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for row in frame.reset_index().to_dict("records"):
        spec = SYMBOLS_BY_SYMBOL.get(str(row.get("symbol")))
        close = row.get("close")
        observation = row.get("date")
        if spec is None or close is None or pd.isna(close) or pd.isna(observation):
            continue
        rows.append(
            {
                "series_id": spec.series_id,
                "observation_date": _as_date(observation),
                "value": float(close),
                "unit": spec.unit,
                "source": source,
                "provider": PROVIDER_ROUTES[route],
            }
        )
    return rows


def rows_from_fred(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Melt FRED's wide frame (one column per requested id) into stored rows."""
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for fred_id, spec in FRED_BY_ID.items():
        if fred_id not in frame.columns:
            continue
        series = frame[fred_id].dropna()
        for observation, value in series.items():
            rows.append(
                {
                    "series_id": spec.series_id,
                    "observation_date": _as_date(observation),
                    "value": float(value),
                    "unit": spec.unit,
                    "source": "FRED",
                    "provider": PROVIDER_ROUTES["fred"],
                }
            )
    return rows


def rows_from_risk_premium(frame: pd.DataFrame, observation_date: date) -> list[dict[str, Any]]:
    """The United States row of FMP's country risk premium frame, as one observation."""
    if frame is None or frame.empty or "country" not in frame.columns:
        return []
    spec = SPECS_BY_ID["ERP_US"]
    us = frame[frame["country"].astype(str).str.fullmatch("United States", case=False)]
    if us.empty:
        return []
    value = us.iloc[0].get("total_equity_risk_premium")
    if value is None or pd.isna(value):
        return []
    return [
        {
            "series_id": spec.series_id,
            "observation_date": observation_date,
            "value": float(value),
            "unit": spec.unit,
            "source": "FMP",
            "provider": PROVIDER_ROUTES["risk_premium"],
        }
    ]


def sector_rows(frame: pd.DataFrame, source: str = "FMP") -> list[dict[str, Any]]:
    """Normalize an etf.sectors frame into raw.macro_etf_sectors rows."""
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        symbol = row.get("symbol")
        sector = row.get("sector")
        weight = row.get("weight")
        if not symbol or not sector or weight is None or pd.isna(weight):
            continue
        rows.append(
            {
                "symbol": str(symbol).upper(),
                "sector": str(sector),
                "value": float(weight),
                "source": source,
            }
        )
    return rows


# --- Collection (shared by the ETL stage and the API live fallback) ---------------


def collect_rows(
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
    include_fmp: bool = True,
    include_fred: bool = True,
    include_sectors: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Fetch every registered series; returns (rows, sector rows, stats).

    ``stats`` carries ``attempted``/``skipped`` (series counts, for
    ``stage_exit_code``), ``errors`` (failed fetches) and ``empty`` (fetches
    that answered but held no rows). A missing provider key skips its series
    rather than failing: supporting data must not sink the nightly.
    """
    # Imported here so the registry module stays import-cheap for the API.
    from src.crispdm.openbb_client import (
        _has_fmp_key,
        _has_fred_key,
        macro_equity_history,
        macro_etf_history,
        macro_etf_sectors,
        macro_fred,
        macro_risk_premium,
        macro_treasury_rates,
    )

    stats = {"attempted": 0, "skipped": 0, "errors": 0, "empty": 0}
    rows: list[dict[str, Any]] = []
    sector_list: list[dict[str, Any]] = []
    today = date.today()
    start = (today - timedelta(days=max(lookback_days, 1))).isoformat()
    end = today.isoformat()

    fmp_specs = [spec for spec in SPECS if spec.source == "FMP"]
    if include_fmp:
        if not _has_fmp_key():
            stats["skipped"] += len(fmp_specs) + len(SECTOR_SYMBOLS) * int(include_sectors)
            print(
                "  No FMP key configured; skipping the FMP macro series. Set fmp_api_key "
                "in ObbCredentials.json."
            )
        else:
            treasury_specs = [spec for spec in fmp_specs if spec.route == "treasury"]
            stats["attempted"] += len(treasury_specs)
            try:
                frame = macro_treasury_rates(start_date=start, end_date=end)
                if frame is None or frame.empty:
                    stats["empty"] += 1
                else:
                    rows.extend(rows_from_treasury(frame))
            except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  Error fetching the UST curve: {exc}")

            for route, call in (
                ("equity", lambda: macro_equity_history(EQUITY_SYMBOLS, start, end)),
                ("etf", lambda: macro_etf_history(ETF_SYMBOLS, start, end)),
            ):
                route_specs = [spec for spec in fmp_specs if spec.route == route]
                if not route_specs:
                    continue
                stats["attempted"] += len(route_specs)
                try:
                    frame = call()
                    if frame is None or frame.empty:
                        stats["empty"] += 1
                    else:
                        rows.extend(rows_from_history(frame, "FMP", route))
                except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
                    stats["errors"] += 1
                    if stats["errors"] <= 5:
                        print(f"  Error fetching {route} history: {exc}")

            stats["attempted"] += 1  # ERP_US
            try:
                frame = macro_risk_premium()
                if frame is None or frame.empty:
                    stats["empty"] += 1
                else:
                    rows.extend(rows_from_risk_premium(frame, today))
            except Exception as exc:  # noqa: BLE001 - best-effort enrichment
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  Error fetching country risk premia: {exc}")

            if include_sectors:
                for symbol in SECTOR_SYMBOLS:
                    stats["attempted"] += 1
                    try:
                        frame = macro_etf_sectors(symbol)
                        if frame is None or frame.empty:
                            stats["empty"] += 1
                        else:
                            sector_list.extend(sector_rows(frame))
                    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
                        stats["errors"] += 1
                        if stats["errors"] <= 5:
                            print(f"  Error fetching sectors for {symbol}: {exc}")
    else:
        stats["skipped"] += len(fmp_specs)

    fred_specs = [spec for spec in SPECS if spec.source == "FRED"]
    if include_fred:
        if not _has_fred_key():
            stats["skipped"] += len(fred_specs)
            print(
                "  No FRED key configured; skipping the FRED macro series. Set fred_api_key "
                "in ObbCredentials.json."
            )
        else:
            stats["attempted"] += len(fred_specs)
            try:
                frame = macro_fred(FRED_IDS, start_date=start, end_date=end)
                if frame is None or frame.empty:
                    stats["empty"] += 1
                else:
                    rows.extend(rows_from_fred(frame))
            except Exception as exc:  # noqa: BLE001 - one source must not stop the rest
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  Error fetching FRED series: {exc}")
    else:
        stats["skipped"] += len(fred_specs)

    return rows, sector_list, stats


# --- Read-side assembly ----------------------------------------------------------


def latest_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest observation per series: {series_id: {value, as_of, unit, source, ...}}."""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        series_id = row.get("series_id")
        observation = row.get("observation_date")
        if not series_id or observation is None:
            continue
        as_of = _as_date(observation)
        current = latest.get(series_id)
        if current is not None and current["as_of"] >= as_of:
            continue
        latest[series_id] = {
            "value": float(row["value"]),
            "as_of": as_of,
            "unit": row.get("unit") or "",
            "source": row.get("source") or "",
            "provider": row.get("provider") or "",
        }
    return latest


def build_inputs(latest: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One entry per memo input (and stored extra), in memo order per group.

    Status is ``Observed`` when a value is at hand, else ``UNVERIFIED`` with
    either the provider-level reason (no source exists) or the staging reason
    (source exists but nothing is stored yet).
    """
    entries: list[dict[str, Any]] = []
    for group in GROUPS:
        group_specs = [spec for spec in SPECS if spec.group == group]
        ordered_ids = list(DOC_ORDER.get(group, ()))
        ordered_ids.extend(entry.series_id for entry in DERIVED if entry.group == group)
        ordered_ids.extend(
            spec.series_id for spec in group_specs if spec.series_id not in ordered_ids
        )
        ordered_ids.extend(entry.series_id for entry in UNAVAILABLE if entry.group == group)
        seen: set[str] = set()
        for series_id in ordered_ids:
            if series_id in seen:
                continue
            seen.add(series_id)
            entries.append(_entry_for(series_id, group, latest))
    return entries


def _base_entry(series_id: str, group: str) -> dict[str, Any]:
    spec = SPECS_BY_ID.get(series_id)
    derived = DERIVED_BY_ID.get(series_id)
    unavailable = UNAVAILABLE_BY_ID.get(series_id)
    if spec is not None:
        return {
            "id": spec.series_id,
            "label": spec.label,
            "group": group,
            "unit": spec.unit,
            "source": spec.source,
            "note": spec.note,
            "doc_input": spec.doc_input,
            "status": "UNVERIFIED",
            "value": None,
            "as_of": None,
            "reason": "not stored yet; run scripts.populate_macro_inputs",
        }
    if derived is not None:
        return {
            "id": derived.series_id,
            "label": derived.label,
            "group": group,
            "unit": derived.unit,
            "source": "derived",
            "note": derived.note,
            "doc_input": derived.doc_input,
            "status": "UNVERIFIED",
            "value": None,
            "as_of": None,
            "reason": "inputs missing; run scripts.populate_macro_inputs",
            "formula": derived.formula,
        }
    if unavailable is not None:
        return {
            "id": unavailable.series_id,
            "label": unavailable.label,
            "group": group,
            "unit": None,
            "source": None,
            "note": "",
            "doc_input": True,
            "status": "UNVERIFIED",
            "value": None,
            "as_of": None,
            "reason": unavailable.reason,
        }
    raise KeyError(f"unknown macro input id: {series_id}")


def _entry_for(
    series_id: str, group: str, latest: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    entry = _base_entry(series_id, group)
    derived = DERIVED_BY_ID.get(series_id)
    if derived is None:
        hit = latest.get(series_id)
        if hit is not None:
            entry.update(
                status="Observed",
                value=hit["value"],
                as_of=hit["as_of"],
                unit=hit["unit"] or entry["unit"],
                source=hit["source"] or entry["source"],
                reason=None,
            )
        return entry

    values = {name: latest[name]["value"] for name in derived.inputs if name in latest}
    if len(values) != len(derived.inputs):
        return entry
    as_of = min(latest[name]["as_of"] for name in derived.inputs)
    entry.update(
        status="Observed",
        value=float(derived.compute(values)),
        as_of=as_of,
        reason=None,
    )
    return entry


def as_of_stamp(latest: Mapping[str, Mapping[str, Any]]) -> str | None:
    """ISO date of the newest observation across every stored series."""
    if not latest:
        return None
    return max(hit["as_of"] for hit in latest.values()).isoformat()


def financials_weight(sector_rows_: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Financial-sector weight per benchmark ETF, from raw.macro_etf_sectors rows."""
    weights: dict[str, float] = {}
    for row in sector_rows_:
        sector = str(row.get("sector", ""))
        weight = row.get("value", row.get("weight"))
        if "financial" not in sector.lower() or weight is None:
            continue
        symbol = str(row.get("symbol", "")).upper()
        weights[symbol] = weights.get(symbol, 0.0) + float(weight)
    return weights


# --- Memo rendering --------------------------------------------------------------


def format_value(value: float | None, unit: str | None) -> str | None:
    if value is None:
        return None
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "bp":
        return f"{value:+.0f}bp"
    if unit == "ratio":
        return f"{value:.1f}"
    if unit == "index points":
        return f"{value:.2f}"
    if unit == "billions USD":
        # The RRP balance can drain to near zero, where one decimal hides the signal.
        return f"${value:.2f}B" if abs(value) < 10 else f"${value:,.1f}B"
    if unit in ("USD", "USD/oz", "USD/bbl", "USD/MMBtu"):
        return f"${value:,.2f}"
    return f"{value}"


def _markdown_item(entry: Mapping[str, Any]) -> str:
    label = f"`{entry['label']}`"
    if entry["status"] == "Observed":
        rendered = format_value(entry["value"], entry["unit"]) or ""
        if entry["source"] == "derived":
            provenance = f"derived, {entry['as_of']}"
        else:
            provenance = f"{entry['source']}, {entry['as_of']}"
        text = f"{label} {rendered} **Observed** ({provenance})"
        if entry.get("note"):
            text += f" — {entry['note']}"
        return text
    return f"{label} **UNVERIFIED** ({entry['reason']})"


def render_markdown(
    inputs: Iterable[Mapping[str, Any]],
    as_of: str | None,
    financials: Mapping[str, float] | None = None,
) -> str:
    """The memo's Inputs block with every token valued and labelled."""
    by_id = {str(entry["id"]): entry for entry in inputs}
    lines = [f"- **as_of**: `{as_of or 'unknown'}`"]
    for group in GROUPS:
        items = [
            _markdown_item(by_id[series_id])
            for series_id in DOC_ORDER.get(group, ())
            if series_id in by_id
        ]
        if group == "benchmarks":
            items.append(_benchmarks_caveat(financials))
        lines.append(f"- **{GROUP_TITLES[group]}**: " + " · ".join(items))
    return "\n".join(lines)


def _benchmarks_caveat(financials: Mapping[str, float] | None) -> str:
    parts = []
    for symbol in SECTOR_SYMBOLS:
        weight = (financials or {}).get(symbol)
        if weight is None:
            parts.append(f"{symbol} financials weight **UNVERIFIED** (no sector snapshot stored)")
        else:
            parts.append(f"{symbol} financials {weight * 100:.1f}% **Observed**")
    concentration = " · ".join(parts)
    return (
        f"proxy caveat — {concentration}; duration and call exposure "
        "**UNVERIFIED** (no provider series)"
    )
