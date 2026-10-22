"""Data-driven autofill for the investment-analysis worksheet.

Steps 1-17 (and the final recommendation) are normally written by the analyst. This
module offers a deterministic starting point built from the same OpenBB commands the
worksheet's context panel reads, trying FMP first and yfinance where FMP does not answer
(a missing key, a premium-only endpoint or an empty payload). The latest warehouse feature,
score, DCF and periodic-financial rows fill provider gaps and supply the stored dividend
coverage, payout and model-quality fields. Every field is filled, but the values are
heuristics over reported data rather than forecasts: the *Sources* field of each section
names the endpoints used, and the final *Data quality* note lists anything that could not
be read so nothing looks observed when it was inferred.

Nothing here writes to the warehouse. Like ``app.llm_client``, it returns a payload for
the page to place in the form; the analyst reviews it and saves through the normal path,
which still enforces every Final rule (including the steps 1-17 gate and the recommendation
sequence rule).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from app import analysis_schema as schema
from src.crispdm import analogs
from src.crispdm import openbb_client as client

#: Commands whose frame is one row per period rather than one row per security.
_PERIOD_COMMANDS = ("income", "balance", "cash")
#: Commands kept as row lists because their sections need more than the latest row.
_ROW_COMMANDS = ("insider", "peers", "price_target", "prices")


@dataclass
class CompanyData:
    """Everything one autofill run read, plus which provider answered each command."""

    ticker: str
    profile: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)
    consensus: dict = field(default_factory=dict)
    ratios: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    income: list[dict] = field(default_factory=list)
    balance: list[dict] = field(default_factory=list)
    cash: list[dict] = field(default_factory=list)
    insider: list[dict] = field(default_factory=list)
    peers: list[dict] = field(default_factory=list)
    price_target: list[dict] = field(default_factory=list)
    prices: list[dict] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    index_options: list[dict] = field(default_factory=list)
    vix_term: dict = field(default_factory=dict)
    options_requested: bool = False
    providers: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


def fetch_company(ticker, *, command=None, today=None, include_options=False) -> CompanyData:
    """Read every command the worksheet autofill needs for ``ticker``.

    ``command`` is injectable for tests (``client.equity_command`` by default). A command
    that fails is recorded in ``failures`` and the rest of the worksheet still builds, so
    one premium-only endpoint cannot block steps 1-17. Options positioning is opt-in:
    it adds a chain read plus SPY/VIX proxies and never changes the recommendation.
    """
    command = command or client.equity_command
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    start = (today - pd.Timedelta(days=4 * 365)).date()
    data = CompanyData(ticker=ticker)

    singles = ("profile", "quote", "consensus", "ratios", "metrics")
    statements = _PERIOD_COMMANDS
    for name in (*singles, *statements):
        provider, rows, error = _read(command, name, ticker)
        if provider is None:
            if error:
                data.failures[name] = error
            continue
        data.providers[name] = provider
        if name in statements:
            setattr(data, name, rows)
        else:
            setattr(data, name, rows[0] if rows else {})

    for name in ("insider", "peers", "price_target"):
        provider, rows, error = _read(command, name, ticker)
        if provider is None:
            if error:
                data.failures[name] = error
        else:
            data.providers[name] = provider
            setattr(data, name, rows)

    provider, rows, error = _read(
        command, "prices", ticker, start_date=str(start), end_date=str(today.date())
    )
    if provider is not None:
        data.providers["prices"] = provider
        data.prices = _price_rows(rows)
    elif error:
        data.failures["prices"] = error

    if include_options:
        data.options_requested = True
        provider, rows, error = _read(command, "options", ticker)
        if provider is not None:
            data.providers["options"] = provider
            data.options = rows
        elif error:
            data.failures["options"] = error

        provider, rows, error = _read(command, "options", "SPY")
        if provider is not None:
            data.providers["index_options"] = provider
            data.index_options = rows
        elif error:
            data.failures["index_options"] = error

        closes = {}
        for symbol, key in (("^VIX", "vix"), ("^VIX3M", "vix3m")):
            provider, rows, error = _read(
                command,
                "index_prices",
                symbol,
                start_date=str((today - pd.Timedelta(days=30)).date()),
                end_date=str(today.date()),
            )
            if provider is not None:
                prices = _price_rows(rows)
                if prices:
                    data.providers[f"index_{key}"] = provider
                    closes[key] = prices[-1]
            elif error:
                data.failures[f"index_{key}"] = error
        if "vix" in closes and "vix3m" in closes:
            data.vix_term = {
                "vix": closes["vix"]["close"],
                "vix3m": closes["vix3m"]["close"],
                "as_of": str(closes["vix"]["date"].date()),
            }
    return data


def _read(command, name, ticker, **kwargs):
    try:
        provider, frame = command(name, ticker, **kwargs)
    except Exception as exc:  # noqa: BLE001 - a failed source must not block the rest
        return None, [], f"{type(exc).__name__}: {exc}"
    if isinstance(frame, pd.DataFrame) and frame.index.name:
        # Price history arrives with the date as a named index, which ``to_dict`` drops.
        frame = frame.reset_index()
    rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
    return provider, [_clean(row) for row in rows], None


def _clean(row: dict) -> dict:
    """Turn pandas/numpy values into plain Python, with missing values left out."""
    clean = {}
    for key, value in row.items():
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        if value is pd.NaT:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, pd.Timestamp):
            value = value.date()
        clean[key] = value
    return clean


def _price_rows(rows) -> list[dict]:
    prices = []
    for row in rows:
        date = row.get("date") or row.get("period_ending")
        # Adjusted closes reinvest dividends, so momentum, volatility and the analog
        # windows are total returns rather than price changes.
        close = _num(_first(row, "adj_close", "adjusted_close", "close", "close_price"))
        if date is not None and close is not None:
            prices.append({"date": pd.Timestamp(date), "close": close})
    return sorted(prices, key=lambda item: item["date"])


# --- options positioning (opt-in, supporting evidence only) ------------------------

OPTIONS_NOT_REQUESTED = (
    "Not requested (enable options positioning before auto-completing the worksheet)."
)
OPTIONS_UNAVAILABLE = "N/A - no options data was returned for this security."


def _option_contracts(rows, today, *, min_dte=7, max_dte=120) -> list[dict]:
    """Normalise an OpenBB options chain, dropping the contracts that distort metrics."""
    contracts = []
    for row in rows or []:
        kind = str(row.get("option_type") or "").strip().lower()
        if kind not in ("call", "put"):
            continue
        expiry = pd.to_datetime(row.get("expiration"), errors="coerce")
        dte = _num(row.get("dte"))
        if dte is None and not pd.isna(expiry):
            dte = (expiry.normalize() - today).days
        if dte is None:
            continue
        dte = int(dte)
        if not min_dte <= dte <= max_dte:
            continue
        strike = _num(row.get("strike"))
        if strike is None or strike <= 0:
            continue
        iv = _num(row.get("implied_volatility"))
        # yfinance returns implausible values (often > 100%) for same-day contracts.
        if iv is not None and not 0.01 <= iv <= 3.0:
            iv = None
        bid, ask = _num(row.get("bid")), _num(row.get("ask"))
        mid = (bid + ask) / 2 if bid and ask and ask >= bid > 0 else None
        contracts.append(
            {
                "is_call": kind == "call",
                "dte": dte,
                "expiry": None if pd.isna(expiry) else expiry.date(),
                "strike": strike,
                "iv": iv,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": _num(row.get("last_trade_price")),
                "volume": _num(row.get("volume")) or 0.0,
                "oi": _num(row.get("open_interest")) or 0.0,
                "underlying": _num(row.get("underlying_price")),
            }
        )
    return contracts


def _median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def _put_call_ratio(contracts):
    near = [contract for contract in contracts if contract["dte"] <= 60] or contracts
    calls = [contract for contract in near if contract["is_call"]]
    puts = [contract for contract in near if not contract["is_call"]]
    call_volume = sum(contract["volume"] for contract in calls)
    put_volume = sum(contract["volume"] for contract in puts)
    call_oi = sum(contract["oi"] for contract in calls)
    put_oi = sum(contract["oi"] for contract in puts)
    return (
        put_volume / call_volume if call_volume else None,
        put_oi / call_oi if call_oi else None,
    )


def _expiries(contracts):
    return sorted({contract["dte"] for contract in contracts})


def _front_back(contracts):
    dtes = _expiries(contracts)
    if not dtes:
        return None, None
    front = dtes[0]
    back = min(dtes, key=lambda dte: abs(dte - 90))
    if back <= front:
        back = dtes[-1] if dtes[-1] > front else None
    return front, back


def _atm_iv(contracts, dte, spot):
    group = [
        contract for contract in contracts if contract["dte"] == dte and contract["iv"] is not None
    ]
    if not group or spot is None or spot <= 0:
        return None
    strike = min({contract["strike"] for contract in group}, key=lambda value: abs(value - spot))
    ivs = [contract["iv"] for contract in group if contract["strike"] == strike]
    return sum(ivs) / len(ivs) if ivs else None


def _atm_straddle(contracts, dte, spot):
    group = [contract for contract in contracts if contract["dte"] == dte]
    if not group or spot is None or spot <= 0:
        return None
    strike = min({contract["strike"] for contract in group}, key=lambda value: abs(value - spot))
    prices = []
    for is_call in (True, False):
        leg = [
            contract
            for contract in group
            if contract["strike"] == strike and contract["is_call"] == is_call
        ]
        if not leg:
            return None
        price = leg[0]["mid"] if leg[0]["mid"] is not None else leg[0]["last"]
        if price is None:
            return None
        prices.append(price)
    return sum(prices)


def _norm_cdf(value):
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _option_delta(contract, spot, rate):
    iv = contract["iv"]
    if iv is None or spot is None or spot <= 0 or contract["strike"] <= 0:
        return None
    years = max(contract["dte"], 1) / 365.0
    volatility = iv * math.sqrt(years)
    if volatility <= 0:
        return None
    d1 = (math.log(spot / contract["strike"]) + (rate + 0.5 * iv * iv) * years) / volatility
    return _norm_cdf(d1) if contract["is_call"] else _norm_cdf(d1) - 1.0


def _skew(contracts, dte, spot, rate):
    group = [
        contract for contract in contracts if contract["dte"] == dte and contract["iv"] is not None
    ]
    puts = [
        (contract, _option_delta(contract, spot, rate))
        for contract in group
        if not contract["is_call"]
    ]
    calls = [
        (contract, _option_delta(contract, spot, rate)) for contract in group if contract["is_call"]
    ]
    puts = [(contract, delta) for contract, delta in puts if delta is not None]
    calls = [(contract, delta) for contract, delta in calls if delta is not None]
    if not puts or not calls:
        return None, None, None
    put, _ = min(puts, key=lambda item: abs(item[1] + 0.25))
    call, _ = min(calls, key=lambda item: abs(item[1] - 0.25))
    return put["iv"], call["iv"], put["iv"] - call["iv"]


def _option_liquidity(contracts):
    near = [contract for contract in contracts if contract["dte"] <= 60] or contracts
    total_oi = sum(contract["oi"] for contract in near)
    strikes = len({contract["strike"] for contract in near})
    spreads = [
        (contract["ask"] - contract["bid"]) / contract["mid"]
        for contract in near
        if contract["mid"]
        and contract["bid"] is not None
        and contract["ask"] is not None
        and contract["ask"] > contract["bid"]
    ]
    return total_oi, strikes, _median(spreads)


def _options_block(data, price, today, macro) -> dict:
    """Options metrics as worksheet text.

    The block is deliberately descriptive: it never feeds ``_risk``, ``_risk_score``,
    ``_recommendation`` or the factor scores, so adding options cannot change the call.
    """
    if not data.options_requested:
        blank = OPTIONS_NOT_REQUESTED
        return {
            "status": "Unavailable",
            "macro_pcr": blank,
            "macro_vix": blank,
            "implied_move": blank,
            "positioning": blank,
            "iv": blank,
            "skew": blank,
            "term": blank,
            "liquidity": blank,
        }

    contracts = _option_contracts(data.options, today)
    index_contracts = _option_contracts(data.index_options, today)
    index_pcr_volume, index_pcr_oi = _put_call_ratio(index_contracts)
    if index_contracts:
        macro_pcr = (
            f"SPY proxy: {_decimal(index_pcr_volume)} volume PCR / "
            f"{_decimal(index_pcr_oi)} open-interest PCR (contracts up to 60 DTE)."
        )
    else:
        macro_pcr = "N/A - index options unavailable."

    vix = _num(data.vix_term.get("vix"))
    vix3m = _num(data.vix_term.get("vix3m"))
    if vix is not None and vix3m is not None:
        slope = vix3m - vix
        shape = "contango" if slope > 0 else "backwardation" if slope < 0 else "flat"
        macro_vix = (
            f"VIX {vix:.2f} vs VIX3M {vix3m:.2f} ({slope:+.2f}; {shape}) as of "
            f"{data.vix_term.get('as_of')}."
        )
    else:
        macro_vix = "N/A - VIX/VIX3M history unavailable."

    result = {
        "status": "Unavailable",
        "macro_pcr": macro_pcr,
        "macro_vix": macro_vix,
        "implied_move": OPTIONS_UNAVAILABLE,
        "positioning": OPTIONS_UNAVAILABLE,
        "iv": OPTIONS_UNAVAILABLE,
        "skew": OPTIONS_UNAVAILABLE,
        "term": OPTIONS_UNAVAILABLE,
        "liquidity": OPTIONS_UNAVAILABLE,
    }
    if not contracts:
        return result

    spot = _median([contract["underlying"] for contract in contracts])
    if spot is None or spot <= 0:
        spot = price
    front, back = _front_back(contracts)
    rate = (_macro_value(macro, "UST_10Y") or 4.0) / 100.0
    atm_front = _atm_iv(contracts, front, spot) if front is not None else None
    atm_back = _atm_iv(contracts, back, spot) if back is not None else None
    realized = _volatility(data.prices)
    iv_ratio = _ratio(atm_front, realized)
    straddle = _atm_straddle(contracts, front, spot) if front is not None else None
    pcr_volume, pcr_oi = _put_call_ratio(contracts)
    put_iv, call_iv, skew = (
        _skew(contracts, front, spot, rate) if front is not None else (None, None, None)
    )
    total_oi, strike_count, spread = _option_liquidity(contracts)

    expiry = next((contract["expiry"] for contract in contracts if contract["dte"] == front), None)
    move = _ratio(straddle, spot)
    if move is None and atm_front is not None and front is not None:
        # Fallback: lognormal approximation of the ATM straddle.
        move = 0.7979 * atm_front * math.sqrt(front / 365.0)
    if move is None:
        implied_move = "N/A - no ATM straddle quote."
    else:
        implied_move = f"+/-{_pct(move)} by {expiry} ({front} DTE, ATM straddle)."

    if atm_front is None:
        iv_text = "N/A - implied volatility unavailable."
    elif iv_ratio is None:
        iv_text = f"ATM IV {_pct(atm_front)} ({front} DTE); realized volatility unavailable."
    else:
        iv_text = (
            f"ATM IV {_pct(atm_front)} ({front} DTE) vs {_pct(realized)} realized "
            f"(IV/RV {_x(iv_ratio, 2)})."
        )

    if skew is None:
        skew_text = "N/A - 25-delta quotes unavailable."
    else:
        skew_text = (
            f"25-delta put IV {_pct(put_iv)} vs call IV {_pct(call_iv)} "
            f"({skew * 100:+.1f} vol pts)."
        )

    if front is None or back is None or atm_front is None or atm_back is None:
        term_text = "N/A - two expiries with implied volatility are needed."
    else:
        slope = atm_back - atm_front
        shape = "contango" if slope > 0 else "backwardation" if slope < 0 else "flat"
        term_text = (
            f"Front {_pct(atm_front)} ({front} DTE) vs {_pct(atm_back)} ({back} DTE); "
            f"slope {slope * 100:+.1f} vol pts ({shape})."
        )

    liquidity_text = f"Open interest {total_oi:,.0f} across {strike_count} strikes (<=60 DTE)"
    liquidity_text += (
        f"; median bid-ask {_pct(spread)} of mid."
        if spread is not None
        else "; no two-sided quotes to measure spreads."
    )

    parts = []
    if pcr_volume is not None:
        parts.append(f"PCR {_decimal(pcr_volume)} volume / {_decimal(pcr_oi)} open interest")
    if skew is not None:
        parts.append(f"25-delta skew {skew * 100:+.1f} vol pts")
    if atm_front is not None:
        parts.append(
            f"ATM IV {_pct(atm_front)} ({_x(iv_ratio, 2)} realized)"
            if iv_ratio is not None
            else f"ATM IV {_pct(atm_front)}"
        )
    parts.append(f"implied move {implied_move.rstrip('.')}")
    positioning = (
        "; ".join(parts)
        + ". Descriptive positioning only; it does not change the recommendation, the "
        "risk score or the factor scores."
    )

    result.update(
        status="Observed" if atm_front is not None else "Derived",
        implied_move=implied_move,
        positioning=positioning,
        iv=iv_text,
        skew=skew_text,
        term=term_text,
        liquidity=liquidity_text,
    )
    return result


def load_macro(query=None) -> dict:
    """Latest observation per series from ``raw.macro_series``, keyed by series id.

    Missing tables or an empty warehouse yield ``{}`` rather than an error: the macro
    section then states that the supporting inputs have not been loaded.
    """
    if query is None:
        from app import ui  # local import: keeps the builder importable without Streamlit

        query = ui.query
    try:
        frame = query(
            "SELECT DISTINCT ON (series_id) series_id, value, as_of, source "
            "FROM raw.macro_series ORDER BY series_id, as_of DESC"
        )
    except Exception:  # noqa: BLE001 - an unloaded warehouse is not a page failure
        return {}
    return {
        str(row["series_id"]): {
            "value": _num(row.get("value")),
            "as_of": row.get("as_of"),
            "source": row.get("source"),
        }
        for row in frame.to_dict("records")
    }


def load_warehouse(ticker, query=None) -> dict:
    """Latest warehouse context for one ticker, used as a fallback and cross-check.

    The live provider commands remain the primary source. The stored feature row, model
    scores, FMP DCF estimate and recent periodic financials fill gaps when a provider
    lacks a ratio or statement, and the score/quality fields are surfaced in the written
    sections. Missing relations or an empty warehouse yield ``{}`` rather than an error.
    """
    if query is None:
        from app import ui  # local import: keeps the builder importable without Streamlit

        query = ui.query
    try:
        security = query(
            "SELECT CAST(security_id AS text) AS security_id FROM reference.securities "
            "WHERE ticker = :t AND active "
            "ORDER BY (security_type = 'common_stock') DESC, security_id LIMIT 1",
            {"t": ticker},
        )
    except Exception:  # noqa: BLE001 - an unloaded warehouse is not a page failure
        return {}
    if security.empty:
        return {}
    security_id = str(security.iloc[0]["security_id"])

    def one(sql):
        try:
            frame = query(sql, {"sid": security_id})
        except Exception:  # noqa: BLE001 - each table is optional
            return {}
        if frame.empty:
            return {}
        return _clean(frame.iloc[0].to_dict())

    def many(sql):
        try:
            frame = query(sql, {"sid": security_id})
        except Exception:  # noqa: BLE001 - each table is optional
            return []
        return [_clean(row) for row in frame.to_dict("records")]

    features = one(
        "SELECT as_of_date, current_price, annualized_dividend, dividend_yield, "
        "dividend_growth, earnings_payout, fcf_payout, dividend_coverage, "
        "debt_to_ebitda, interest_coverage, volatility_252d, momentum_252d, "
        "liquidation_discount, legal_rights_score, data_quality_score, "
        "target_sustainable_dividend, price_quality, refinancing_wall, gross_margin, "
        "operating_margin, net_margin, fcf_margin, cash_conversion, net_debt_to_ebitda, "
        "current_ratio, debt_to_equity, pe_ratio, earnings_yield, fcf_yield, price_to_book "
        "FROM model.features WHERE security_id = CAST(:sid AS uuid) "
        "ORDER BY as_of_date DESC LIMIT 1"
    )
    scores = one(
        "SELECT as_of_date, dividend_income_score, sustainability_score, "
        "legal_rights_score, appreciation_score, risk_score, valuation_score, "
        "composite_score, score_coverage, cvs_score, cvs_tier, market_regime, "
        "credit_environment, macro_vintage FROM model.scores "
        "WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date DESC LIMIT 1"
    )
    dcf = one(
        "SELECT as_of_date, dcf, stock_price, reported_currency FROM raw.fmp_dcf "
        "WHERE security_id = CAST(:sid AS uuid) ORDER BY as_of_date DESC LIMIT 1"
    )
    financials = many(
        "SELECT period_end, fiscal_period, revenue, net_income, free_cash_flow "
        "FROM fundamentals.periodic_financials WHERE security_id = CAST(:sid AS uuid) "
        "AND period_end <= CURRENT_DATE ORDER BY period_end DESC LIMIT 8"
    )
    recent, seen = [], set()
    for row in financials:
        period = row.get("period_end")
        if period in seen or (_first(row, "revenue", "net_income", "free_cash_flow") is None):
            continue
        seen.add(period)
        recent.append(row)
    financials = recent[:4]
    return {
        "security_id": security_id,
        "features": features,
        "scores": scores,
        "dcf": dcf,
        "financials": financials,
        "base_rate": _peer_base_rate(query, security_id, ticker, features),
        "own_returns": _own_forward_returns(query, security_id),
    }


def _own_forward_returns(query, security_id):
    """This security's own last complete forward windows, for the fallback table.

    Read from the materialised table so the fallback is measured by the same
    definition as the peer base rate it stands in for.
    """
    try:
        return analogs.own_forward_returns(query, security_id)
    except Exception:  # noqa: BLE001 - a missing forward-return table is not a failure
        return []


def _peer_base_rate(query, security_id, ticker, features):
    """The peer base rate for one ticker, or an empty payload when unavailable.

    The forward-return table is a derived relation, so it may not have been built
    yet; a missing table is a reason to fall back to the security's own history,
    not a reason to fail the page.
    """
    try:
        base_rate = analogs.peer_base_rate(
            query,
            security_id,
            features.get("as_of_date") or pd.Timestamp.now().normalize(),
            ticker=ticker,
        )
    except Exception:  # noqa: BLE001 - a missing forward-return table is not a failure
        return {}
    return analogs.base_rate_payload(base_rate)


# --- value helpers -----------------------------------------------------------------


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _first(row, *keys):
    for key in keys:
        if key in row:
            number = _num(row[key])
            if number is not None:
                return number
    return None


def _text(row, *keys, default=""):
    for key in keys:
        value = row.get(key)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return default


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth(current, prior):
    if current is None or prior in (None, 0):
        return None
    return current / prior - 1


def _total_return(value, price, dividend_yield):
    """Approximate a 12M total return by adding the forward yield to the price return."""
    price_return = _growth(value, price)
    if price_return is None:
        return None
    return price_return + (dividend_yield or 0)


def _ratio_positive(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _outflow(value):
    return None if value is None else abs(value)


def _pct(value, digits=1):
    return "N/A" if value is None else f"{value:.{digits}%}"


def _money(value, currency=""):
    number = _num(value)
    if number is None:
        return "N/A"
    suffix = f" {currency}".rstrip()
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(number) >= scale:
            return f"{number / scale:,.2f}{unit}{suffix}"
    return f"{number:,.2f}{suffix}"


def _x(value, digits=1):
    return "N/A" if value is None else f"{value:.{digits}f}x"


def _decimal(value, digits=2):
    return "N/A" if value is None else f"{value:.{digits}f}"


def _level(value, low, high):
    """Map a metric to the worksheet's Low/Moderate/High ordering."""
    if value is None:
        return "Moderate"
    if value <= low:
        return "Low"
    if value >= high:
        return "High"
    return "Moderate"


def _size(market_cap):
    if market_cap is None:
        return "Mid"
    if market_cap >= 10e9:
        return "Large"
    if market_cap >= 2e9:
        return "Mid"
    return "Small"


def _clamp(value, low=1, high=10):
    return max(low, min(high, int(round(value))))


def _macro_value(macro, series_id):
    entry = (macro or {}).get(series_id) or {}
    return _num(entry.get("value"))


def _macro_note(macro, series_id):
    entry = (macro or {}).get(series_id) or {}
    if entry.get("value") is None:
        return "not loaded"
    as_of = entry.get("as_of")
    return f"{entry['value']:.2f} as of {as_of}" if as_of else f"{entry['value']:.2f}"


def _macro_pct(macro, series_id):
    entry = (macro or {}).get(series_id) or {}
    if entry.get("value") is None:
        return "not loaded"
    return f"{_macro_note(macro, series_id)}%"


# --- the payload -------------------------------------------------------------------


def build_payload(
    ticker: str, data: CompanyData, *, macro=None, warehouse=None, today=None
) -> dict:
    """Fill every worksheet field from ``data``, macro observations and the warehouse."""
    macro = macro or {}
    warehouse = warehouse or {}
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    c = _context(data, today, macro, warehouse)
    sections = schema.empty_payload()["sections"]
    sources = _sources(data)
    if warehouse:
        sources += (
            " Warehouse context: model.features, model.scores, raw.fmp_dcf, "
            "fundamentals.periodic_financials and model.forward_returns."
        )
    confidence = "High" if c["rich"] else ("Medium" if c["some"] else "Low")

    def put(section_id, field_id, value):
        sections[section_id][field_id] = value

    def src(section_id, *extra):
        parts = [sources] if sources else []
        parts.extend(part for part in extra if part)
        sections[section_id]["sources"] = (
            "Auto-generated by app.analysis_autofill. " + " ".join(parts)
        ).strip()

    def conf(section_id, note=""):
        if not schema.SECTION_BY_ID[section_id].has_confidence:
            return
        put(section_id, "confidence", confidence)
        put(
            section_id,
            "confidence_note",
            note or f"Deterministic estimate from {c['source_short']}; no analyst review yet.",
        )

    ccy = c["currency"]
    price = c["price"]
    target = c["target"]
    options = _options_block(data, price, today, macro)
    option_source = (
        "Options: YFINANCE derivatives.options.chains (single name), SPY proxy and "
        "VIX/VIX3M history; descriptive only, not used in the recommendation."
        if data.options_requested
        else ""
    )

    # 1. Investment universe -------------------------------------------------------
    put(
        "universe",
        "universe_filters",
        f"Sector: {c['sector']}; Industry: {c['industry']}; "
        f"Market cap: {_money(c['market_cap'], ccy)} ({_size(c['market_cap'])}); "
        f"Exchange: {c['exchange']}; Country: {c['country']}.",
    )
    put(
        "universe",
        "universe_rationale",
        f"Auto-generated from the company profile: {c['name']} is a {c['industry']} "
        f"company listed on {c['exchange']} with {c['employees']} employees. The screen "
        f"starts from the active dividend-equity universe and keeps {c['sector']} names of "
        f"a similar size, so the comparisons below use like-for-like listings.",
    )
    src("universe")

    # 2. Macro & credit ------------------------------------------------------------
    ig, hy, ust10, ust2 = (
        _macro_value(macro, "IG_OAS"),
        _macro_value(macro, "HY_OAS"),
        _macro_value(macro, "UST_10Y"),
        _macro_value(macro, "UST_2Y"),
    )
    curve = None if ust10 is None or ust2 is None else (ust10 - ust2) * 100
    if macro:
        backdrop = (
            f"10y UST {_macro_pct(macro, 'UST_10Y')}; 2s10s {curve:+.0f}bp; "
            f"IG OAS {_macro_pct(macro, 'IG_OAS')}; HY OAS "
            f"{_macro_pct(macro, 'HY_OAS')}; VIX {_macro_note(macro, 'VIX')}."
            if curve is not None
            else f"IG OAS {_macro_pct(macro, 'IG_OAS')}; HY OAS {_macro_pct(macro, 'HY_OAS')}."
        )
    else:
        backdrop = (
            "Macro inputs are not loaded in raw.macro_series; run the macro stage for a "
            "data-backed backdrop. The credit verdict below is therefore neutral."
        )
    verdict = (
        "Bullish"
        if hy is not None and hy < 3.5 and (ig is None or ig < 1.0)
        else "Bearish"
        if hy is not None and hy > 5.5
        else "Neutral"
    )
    put("macro", "macro_backdrop", backdrop)
    put("macro", "ig_spreads", _macro_pct(macro, "IG_OAS"))
    put("macro", "hy_spreads", _macro_pct(macro, "HY_OAS"))
    put(
        "macro",
        "cds_trend",
        "Improving"
        if hy is not None and hy < 3.5
        else "Deteriorating"
        if hy is not None and hy > 5.5
        else "Flat",
    )
    put(
        "macro",
        "default_rates",
        "Not reported by the selected endpoints; HY OAS is used as the credit-stress proxy.",
    )
    put(
        "macro",
        "distressed_ratio",
        "Not reported by the selected endpoints; read it as the share of HY trading above "
        "1,000bp and re-check before sizing.",
    )
    put(
        "macro",
        "refinancing_wall",
        "Not reported by the selected endpoints; the debt maturity schedule in the 10-K "
        "is the source of truth for near-term maturities.",
    )
    put("macro", "index_put_call_ratio", options["macro_pcr"])
    put("macro", "vix_term_structure", options["macro_vix"])
    put("macro", "credit_verdict", verdict)
    put(
        "macro",
        "credit_rationale",
        f"Credit conditions are read from the latest stored OAS series: IG "
        f"{_macro_pct(macro, 'IG_OAS')} and HY {_macro_pct(macro, 'HY_OAS')}. "
        f"A {'tight' if verdict == 'Bullish' else 'wide' if verdict == 'Bearish' else 'mid-range'} "
        f"HY spread maps to a {verdict.lower()} credit verdict; CDS and default-rate detail "
        f"is not available from the selected endpoints.",
    )
    conf("macro", "OAS inputs are stored observations; default and CDS detail is unavailable.")
    src(
        "macro",
        "Macro series: raw.macro_series (IG_OAS, HY_OAS, UST_2Y, UST_10Y, VIX).",
        option_source,
    )

    # 3. Industry analysis ---------------------------------------------------------
    peers_text = c["peers_text"]
    put(
        "industry",
        "industry_outlook",
        f"{c['industry']} outlook is inferred from {c['name']}'s reported trajectory: "
        f"revenue {c['growth_word']} {_pct(c['rev_growth'])} over the latest period with a "
        f"{_pct(c['operating_margin'])} operating margin. This is a data-derived starting "
        f"point, not a bottom-up industry forecast; validate end-market demand separately.",
    )
    put(
        "industry",
        "competitive_landscape",
        f"FMP peers: {peers_text}. The issuer's gross margin of "
        f"{_pct(c['gross_margin'])} and operating margin of {_pct(c['operating_margin'])} "
        f"are the comparable points to test against that peer set.",
    )
    conf("industry")
    src("industry")

    # 4. Industry structure & capital cycle ---------------------------------------
    capex_intensity = _ratio(c["capex"], c["revenue"])
    capex_trend = _growth(c["capex"], c["capex_prior"])
    put(
        "capital_cycle",
        "capacity_growth",
        f"Capex {_money(c['capex'], ccy)} ({_pct(capex_intensity)} of revenue); "
        f"revenue growth {_pct(c['rev_growth'])}.",
    )
    put(
        "capital_cycle",
        "competitor_capex",
        "Increasing"
        if capex_trend is not None and capex_trend > 0.1
        else "Decreasing"
        if capex_trend is not None and capex_trend < -0.1
        else "Stable",
    )
    put(
        "capital_cycle",
        "supply_changes",
        f"Reported capex changed {_pct(capex_trend)} year over year; no industry-wide "
        f"capacity series is available from the selected endpoints.",
    )
    put(
        "capital_cycle",
        "barriers",
        "High"
        if (c["gross_margin"] or 0) >= 0.45
        else "Low"
        if c["gross_margin"] is not None and c["gross_margin"] < 0.15
        else "Moderate",
    )
    put(
        "capital_cycle",
        "utilization",
        "Not reported for this issuer; capex intensity and incremental revenue are the "
        "available proxy.",
    )
    put("capital_cycle", "profitability_trend", c["profitability_trend"])
    put("capital_cycle", "capital_discipline_score", c["capital_discipline"])
    conf("capital_cycle")
    src("capital_cycle")

    # 5. Supply side ---------------------------------------------------------------
    put(
        "supply",
        "supply_analysis",
        f"Supply-side read: capex is {_pct(capex_intensity)} of revenue and changed "
        f"{_pct(capex_trend)} year over year, while gross margin is "
        f"{_pct(c['gross_margin'])}. {c['barrier_sentence']} Industry capacity data is not "
        f"carried by the selected endpoints, so treat this as an issuer-level proxy.",
    )
    conf("supply")
    src("supply")

    # 6. Demand side ---------------------------------------------------------------
    put(
        "demand",
        "demand_analysis",
        f"Demand-side read: revenue {c['growth_word']} {_pct(c['rev_growth'])} to "
        f"{_money(c['revenue'], ccy)} in the latest period, with a {_pct(c['net_margin'])} "
        f"net margin. The peer set ({peers_text}) gives the cross-check; no order-book or "
        f"end-market volume series is available from the selected endpoints.",
    )
    conf("demand")
    src("demand")

    # 7. Consensus expectations ---------------------------------------------------
    put("consensus", "fy_revenue_est", f"{_money(c['fy_revenue'], ccy)} (derived)")
    put("consensus", "fy_eps_est", f"{_num_or_na(c['fy_eps'])} (derived)")
    put("consensus", "next_fy_revenue_est", f"{_money(c['next_fy_revenue'], ccy)} (derived)")
    put("consensus", "next_fy_eps_est", f"{_num_or_na(c['next_fy_eps'])} (derived)")
    put("consensus", "revision_trend", c["revision_trend"])
    put("consensus", "estimate_dispersion", c["dispersion"])
    put(
        "consensus",
        "surprise_implication",
        f"Live forward estimates are premium-only at FMP and are not provided by yfinance, "
        f"so the FY figures are derived by holding the latest reported growth rate "
        f"({_pct(c['rev_growth'])} revenue, {_pct(c['eps_growth'])} EPS). The analyst "
        f"target range of {_money(c['target_low'], ccy)}-{_money(c['target_high'], ccy)} "
        f"is the only market-based expectation gap available, so an earnings surprise "
        f"should be judged against that range, not against a point estimate.",
    )
    put("consensus", "options_implied_move", options["implied_move"])
    src("consensus", option_source)

    # 8. Variant perception -------------------------------------------------------
    put("variant", "consensus_revenue_growth", _pct(c["rev_growth"]))
    put("variant", "consensus_eps_growth", _pct(c["eps_growth"]))
    put("variant", "consensus_margins", c["margin_trend"])
    put(
        "variant",
        "consensus_capital_allocation",
        f"Dividends {_money(c['dividends_paid'], ccy)} and buybacks "
        f"{_money(c['buybacks'], ccy)} over the latest period; capex "
        f"{_pct(capex_intensity)} of revenue.",
    )
    put("variant", "consensus_multiple", f"P/E {_x(c['pe'])}; EV/EBITDA {_x(c['ev_ebitda'])}.")
    put("variant", "my_revenue_growth", _pct(_shift(c["rev_growth"], 0.01)))
    put("variant", "my_eps_growth", _pct(_shift(c["eps_growth"], 0.01)))
    put("variant", "my_margins", c["margin_trend"])
    put(
        "variant",
        "my_capital_allocation",
        f"Same reported payout as consensus, with free cash flow of "
        f"{_money(c['fcf'], ccy)} covering dividends {_money(c['dividends_paid'], ccy)}.",
    )
    put(
        "variant",
        "my_multiple",
        f"Apply the current P/E of {_x(c['pe'])} to the derived EPS path; the analyst "
        f"target implies {_x(c['target_multiple'])} on the same path.",
    )
    put("variant", "options_positioning", options["positioning"])
    put(
        "variant",
        "bullish_variant",
        f"The market may underprice the {_pct(c['fcf_margin'])} free-cash-flow margin and "
        f"{_x(c['cash_conversion'])} cash conversion, which would support a re-rating if "
        f"revenue keeps growing near {_pct(c['rev_growth'])} and the payout stays covered.",
    )
    put(
        "variant",
        "bearish_variant",
        f"The market may overprice the {_x(c['pe'])} P/E if growth slows from "
        f"{_pct(c['rev_growth'])} or the operating margin compresses from "
        f"{_pct(c['operating_margin'])}; a de-rating toward the peer multiple would erase "
        f"the analyst-target upside.",
    )
    put(
        "variant",
        "key_evidence",
        "\n".join(
            [
                f"Revenue growth {_pct(c['rev_growth'])} with operating margin "
                f"{_pct(c['operating_margin'])}.",
                f"Cash conversion {_x(c['cash_conversion'])} and FCF margin "
                f"{_pct(c['fcf_margin'])}.",
                f"Analyst target {_money(target, ccy)} vs price {_money(price, ccy)} "
                f"({_pct(c['upside'])} upside).",
            ]
        ),
    )
    conf("variant")
    src("variant", option_source)

    # 9. Company deep-dive --------------------------------------------------------
    put(
        "company",
        "business_model",
        f"{c['description']} Listed on {c['exchange']} in {c['country']}, "
        f"{c['sector']} / {c['industry']}, with {c['employees']} employees. "
        f"CEO: {c['ceo']}.",
    )
    warehouse_financials = ""
    if c["features_as_of"]:
        sustainable = c["target_sustainable_dividend"]
        sustainability = (
            "sustainable"
            if sustainable == 1
            else "not sustainable"
            if sustainable == 0
            else "unclassified"
        )
        warehouse_financials = (
            f" Stored features ({c['features_as_of']}): earnings payout "
            f"{_pct(c['earnings_payout'])}, FCF payout {_pct(c['fcf_payout'])}, dividend "
            f"cover {_x(c['dividend_coverage'])}, interest cover {_x(c['interest_coverage'])}, "
            f"refinancing wall {_x(c['refinancing_wall'])} and the dividend target is "
            f"{sustainability}. Data quality {_decimal(c['data_quality_score'])}/10 "
            f"({c['price_quality']})."
        )
    if c["scores_as_of"]:
        warehouse_financials += (
            f" Model scores ({c['scores_as_of']}): composite "
            f"{_pct(c['composite_score'])}, sustainability "
            f"{_pct(c['sustainability_score'])}, valuation "
            f"{_pct(c['valuation_score'])}, risk {_pct(c['model_risk_score'])} "
            f"with {_pct(c['score_coverage'])} coverage"
            + (f"; CVS tier {c['cvs_tier']}" if c["cvs_tier"] else "")
            + (
                f"; regime {c['market_regime']}, credit {c['credit_environment']}."
                if c["market_regime"] or c["credit_environment"]
                else "."
            )
        )
    put(
        "company",
        "financial_analysis",
        f"Latest revenue {_money(c['revenue'], ccy)} ({_pct(c['rev_growth'])} YoY), "
        f"operating margin {_pct(c['operating_margin'])}, net margin "
        f"{_pct(c['net_margin'])}. Net debt/EBITDA {_x(c['net_debt_ebitda'])}, current "
        f"ratio {_x(c['current_ratio'])}, debt/equity {_x(c['debt_equity'])}. Free cash "
        f"flow {_money(c['fcf'], ccy)} and cash conversion {_x(c['cash_conversion'])}."
        f"{_dividend_summary(c)}{warehouse_financials}",
    )
    conf("company")
    src("company")

    # 10. Earnings quality -------------------------------------------------------
    put(
        "earnings_quality",
        "cash_conversion",
        f"{_x(c['cash_conversion'])} (CFO {_money(c['cfo'], ccy)} / net income "
        f"{_money(c['net_income'], ccy)})",
    )
    put("earnings_quality", "accrual_ratio", _pct(c["accrual_ratio"]))
    put("earnings_quality", "sbc_pct", _pct(c["sbc_pct"]))
    put(
        "earnings_quality",
        "gaap_gap",
        "No adjusted figures are available from the selected endpoints; reported and "
        "adjusted earnings are treated as equal.",
    )
    put(
        "earnings_quality",
        "working_capital",
        f"Change in working capital {_money(c['working_capital'], ccy)} "
        f"({'source' if (c['working_capital'] or 0) >= 0 else 'use'} of cash).",
    )
    put(
        "earnings_quality",
        "one_time_items",
        "No one-off schedule is available from the selected endpoints. Review the latest "
        "10-K for restructuring, impairment and litigation items before relying on the "
        f"{_x(c['cash_conversion'])} cash-conversion figure.",
    )
    put("earnings_quality", "quality_verdict", c["quality_verdict"])
    put(
        "earnings_quality",
        "red_flags",
        c["red_flags"],
    )
    conf("earnings_quality")
    src("earnings_quality")

    # 11. Competitive advantage --------------------------------------------------
    put("moat", "network_effects", c["moat"]["network_effects"])
    put("moat", "scale_advantage", c["moat"]["scale_advantage"])
    put("moat", "brand_strength", c["moat"]["brand_strength"])
    put("moat", "switching_costs", c["moat"]["switching_costs"])
    put("moat", "cost_leadership", c["moat"]["cost_leadership"])
    put("moat", "regulatory_advantage", c["moat"]["regulatory_advantage"])
    put("moat", "moat_rating", c["moat"]["moat_rating"])
    put("moat", "durability_trend", c["moat"]["durability_trend"])
    conf("moat")
    src("moat")

    # 12. Management assessment --------------------------------------------------
    put(
        "management",
        "track_record",
        f"Revenue {c['growth_word']} {_pct(c['rev_growth'])} over the latest period and "
        f"earnings per share changed {_pct(c['eps_growth'])}; return on equity "
        f"{_pct(c['roe'])} and return on invested capital {_pct(c['roic'])}.",
    )
    put(
        "management",
        "capital_allocation_history",
        f"Dividends {_money(c['dividends_paid'], ccy)}, buybacks "
        f"{_money(c['buybacks'], ccy)}, capex {_money(c['capex'], ccy)} and free cash "
        f"flow {_money(c['fcf'], ccy)} in the latest period.",
    )
    put(
        "management",
        "guidance_accuracy",
        "Not reported by the selected endpoints; compare the next release with the "
        "derived FY figures in step 7.",
    )
    put(
        "management",
        "insider_ownership",
        f"Not reported by the selected endpoints; insider transactions over 12M: "
        f"{c['insider_buys']} buys / {c['insider_sells']} sells.",
    )
    put("management", "insider_transactions", c["insider_signal"])
    put(
        "management",
        "compensation_alignment",
        "No compensation schedule is available from the selected endpoints; the score "
        "reflects reported returns, cash generation and insider activity.",
    )
    put("management", "management_score", c["management_score"])
    conf("management")
    src("management")

    # 13. Valuation --------------------------------------------------------------
    dcf_text = (
        f" The stored FMP DCF is {_money(c['dcf'], ccy)} as of {c['dcf_as_of']} "
        f"({_pct(c['dcf_margin'])} versus the current price), used as an intrinsic-value "
        f"cross-check."
        if c["dcf"] is not None
        else ""
    )
    put(
        "valuation",
        "valuation_methods",
        f"P/E {_x(c['pe'])}, price/book {_x(c['pb'])}, EV/EBITDA {_x(c['ev_ebitda'])}, "
        f"FCF yield {_pct(c['fcf_yield'])} and the {c['target_source']} target "
        f"{_money(target, ccy)}. The target is the anchor; the multiples are the "
        f"cross-check.{dcf_text}",
    )
    put(
        "valuation",
        "key_assumptions",
        f"Revenue grows at the reported {_pct(c['rev_growth'])} and margins hold at "
        f"{_pct(c['operating_margin'])}; the market applies the current {_x(c['pe'])} P/E "
        f"to the derived EPS path. The {c['target_source']} target is assumed to embed a "
        f"discount rate consistent with the current price of {_money(price, ccy)}.",
    )
    put("valuation", "target_price", f"{_money(target, ccy)} ({ccy})")
    put("valuation", "margin_of_safety", _pct(c["upside"]))
    conf("valuation")
    src("valuation")

    # 14. Scenarios --------------------------------------------------------------
    put(
        "scenarios",
        "base_case",
        f"Base: {_money(c['base_case'], ccy)} ({_pct(c['base_return'])}), revenue growth "
        f"{_pct(c['rev_growth'])} and operating margin {_pct(c['operating_margin'])}.",
    )
    put(
        "scenarios",
        "bull_case",
        f"Bull: {_money(c['bull_case'], ccy)} ({_pct(c['bull_return'])}), growth "
        f"accelerates and the multiple expands toward the high analyst target.",
    )
    put(
        "scenarios",
        "bear_case",
        f"Bear: {_money(c['bear_case'], ccy)} ({_pct(c['bear_return'])}), growth stalls "
        f"and the multiple compresses toward the low analyst target.",
    )
    put("scenarios", "scenario_probabilities", "50% / 30% / 20%")
    put("scenarios", "expected_return", _pct(c["expected_return"]))
    conf("scenarios")
    src("scenarios")

    # 15. Historical analogs -----------------------------------------------------
    put("analog", "similar_setups", c["analog_table"])
    put("analog", "base_rate", f"{c['base_rate']:.0f}%")
    if c["analog_source"] == "peer":
        put("analog", "key_differences", _peer_key_differences(c))
        put("analog", "analog_implication", _peer_implication(c))
        conf("analog", _peer_confidence_note(c))
    else:
        put(
            "analog",
            "key_differences",
            f"Today's setup differs from the listed windows in its current P/E of "
            f"{_x(c['pe'])} and free-cash-flow yield of {_pct(c['fcf_yield'])}; those are the "
            f"variables to re-check, not just the total-return path.",
        )
        put(
            "analog",
            "analog_implication",
            f"{c['base_rate']:.0f}% of the listed 12M windows were positive. That is a weak "
            f"base rate from one security's own history, so it supports a probabilistic "
            f"frame rather than a directional conclusion.",
        )
        conf(
            "analog",
            "Base rate uses this security's own 12M windows, not a peer sample.",
        )
    src("analog")

    # 16. Risk decomposition -----------------------------------------------------
    put("risk", "business_risk", c["risk"]["business"])
    put("risk", "valuation_risk", c["risk"]["valuation"])
    put("risk", "balance_sheet_risk", c["risk"]["balance_sheet"])
    put("risk", "macro_risk", c["risk"]["macro"])
    put("risk", "regulatory_risk", c["risk"]["regulatory"])
    put("risk", "liquidity_risk", c["risk"]["liquidity"])
    put("risk", "options_iv", options["iv"])
    put("risk", "options_skew", options["skew"])
    put("risk", "options_term_structure", options["term"])
    put("risk", "options_liquidity", options["liquidity"])
    put("risk", "options_data_status", options["status"])
    put("risk", "overall_risk_score", c["risk_score"])
    put(
        "risk",
        "position_sizing",
        f"Risk score {c['risk_score']}/10 implies a "
        f"{'small (1-2%)' if c['risk_score'] >= 7 else 'moderate (2-3%)' if c['risk_score'] >= 4 else 'full (4-5%)'} "
        f"position; {_dividend_phrase(c)}, and size down further if cover or liquidity weakens.",
    )
    conf("risk")
    src("risk", option_source)

    # 17. Portfolio integration --------------------------------------------------
    put("portfolio", "factor_growth", c["factors"]["growth"])
    put("portfolio", "factor_value", c["factors"]["value"])
    put("portfolio", "factor_quality", c["factors"]["quality"])
    put("portfolio", "factor_momentum", c["factors"]["momentum"])
    put("portfolio", "factor_low_volatility", c["factors"]["low_volatility"])
    put("portfolio", "factor_size", _size(c["market_cap"]))
    put("portfolio", "factor_rate_duration", c["factors"]["rate_duration"])
    put("portfolio", "factor_usd_exposure", c["factors"]["usd_exposure"])
    put(
        "portfolio",
        "existing_tilts",
        f"Auto-generated: compare the {c['sector']} weight and the "
        f"{_size(c['market_cap'])}-cap exposure against the live portfolio before adding.",
    )
    put(
        "portfolio",
        "position_adds",
        f"A {c['factors']['growth'].lower()}-growth, {c['factors']['quality'].lower()}-quality, "
        f"{c['factors']['value'].lower()}-value exposure with a {_pct(c['dividend_yield'])} "
        f"dividend yield.",
    )
    put(
        "portfolio",
        "concentration_risk",
        f"At {_money(c['market_cap'], ccy)} the name is {_size(c['market_cap']).lower()}-cap; "
        f"cap position weight so that the sector plus this name stays within the mandate.",
    )
    put(
        "portfolio",
        "correlation_assessment",
        f"Momentum is {c['factors']['momentum'].lower()} (12M total return) and beta is "
        f"{_x(c['beta'])}; the correlation check must use the live portfolio.",
    )
    src("portfolio")

    # 18. Recommendation & final output -----------------------------------------
    recommendation = c["recommendation"]
    if recommendation:
        thesis = (
            # A name like "Apple Inc." would read as an extra sentence to the
            # three-sentence rule, so periods are dropped from it.
            f"{c['name'].replace('.', '')} trades at {_x(c['pe'])} with a "
            f"{_pct(c['dividend_yield'])} dividend yield and a {_pct(c['fcf_yield'])} "
            f"free-cash-flow yield. "
            f"Reported revenue growth is {_pct(c['rev_growth'])} with a "
            f"{_pct(c['operating_margin'])} operating margin and {_x(c['cash_conversion'])} "
            f"cash conversion. "
            f"The auto-generated {recommendation} call reflects "
            f"{_pct(c['expected_return'])} expected 12M total return, {_pct(c['upside'])} "
            f"price upside to the {c['target_source']} target and a {c['risk_word']}-risk "
            f"profile, while {_dividend_phrase(c)}."
        )
        position_text = (
            f"{'Small (1-2%)' if c['risk_score'] >= 7 else 'Moderate (2-3%)' if c['risk_score'] >= 4 else 'Full (4-5%)'} "
            "position, built in two tranches and reviewed after the next results."
        )
    else:
        thesis = (
            f"{c['name'].replace('.', '')} does not have enough reported data for a "
            "recommendation: an analyst target or FMP DCF plus reported revenue and net "
            "income are required. The auto-complete leaves the recommendation unset for "
            "the analyst to decide."
        )
        position_text = (
            "No position size is proposed because the recommendation is intentionally unset."
        )
    put("final", "thesis", thesis)
    put("final", "recommendation", recommendation)
    put(
        "final",
        "variant_summary",
        f"Consensus embeds {_pct(c['rev_growth'])} revenue growth and "
        f"{_x(c['pe'])} P/E; the data-derived view differs mainly on margin durability "
        f"({c['margin_trend'].lower()}) and cash conversion of "
        f"{_x(c['cash_conversion'])}.",
    )
    put(
        "final",
        "risk_summary",
        f"Risk score {c['risk_score']}/10 ({c['risk_score_source']}). Business "
        f"{c['risk']['business'].lower()}, valuation {c['risk']['valuation'].lower()}, "
        f"balance sheet {c['risk']['balance_sheet'].lower()}, macro "
        f"{c['risk']['macro'].lower()}, regulatory {c['risk']['regulatory'].lower()}, "
        f"liquidity {c['risk']['liquidity'].lower()}.{_dividend_summary(c)}",
    )
    put("final", "position_recommendation", position_text)
    put(
        "final",
        "catalyst_timeline",
        "Next quarterly results and guidance; the next dividend declaration; analyst "
        "estimate revisions; a change in the credit spreads that set the macro backdrop.",
    )
    put(
        "final",
        "kill_switch",
        "A dividend cut, earnings cover below 1.0x, cash conversion below 0.7, net "
        "debt/EBITDA above 3.0x, or two consecutive periods of operating-margin compression.",
    )
    put("final", "confidence_overall", confidence)
    put(
        "final",
        "data_quality",
        f"Providers: {c['provider_summary']}. "
        f"Unavailable: {', '.join(sorted(data.failures)) or 'none'}. "
        f"Warehouse scores are {_pct(c['composite_score'])} composite with "
        f"{_pct(c['score_coverage'])} coverage; stored price quality is {c['price_quality']}. "
        f"Forward estimates are derived rather than observed and insider ownership is not "
        f"reported by the selected endpoints.",
    )
    put(
        "final",
        "forecast_uncertainty",
        "The derived FY path holds the latest growth rate and margin constant; a single "
        "year of history cannot establish persistence, so the range around the base case "
        "is wide.",
    )
    put(
        "final",
        "sensitivity_assumptions",
        f"A 100bp change in the operating margin moves the valuation by roughly "
        f"{_pct(_sensitivity(c))} on an unchanged multiple; the target price is the most "
        f"sensitive assumption.",
    )
    put(
        "final",
        "variant_conviction",
        "Medium: the variant rests on reported cash generation and the analyst target, "
        "not on a differentiated industry forecast.",
    )
    src("final", "All values are deterministic heuristics; review every field before saving.")

    return {"version": schema.SCHEMA_VERSION, "sections": sections}


def _context(data: CompanyData, today, macro, warehouse=None) -> dict:
    profile, quote, cons = data.profile or {}, data.quote or {}, data.consensus or {}
    ratios, metrics = data.ratios or {}, data.metrics or {}
    warehouse = warehouse or {}
    features = warehouse.get("features") or {}
    scores = warehouse.get("scores") or {}
    dcf = warehouse.get("dcf") or {}
    stored = warehouse.get("financials") or []
    inc = data.income[0] if data.income else {}
    prior = data.income[1] if len(data.income) > 1 else {}
    bal = data.balance[0] if data.balance else {}
    cash = data.cash[0] if data.cash else {}
    if not inc and stored:
        inc = stored[0]
        prior = stored[1] if len(stored) > 1 else {}
        if not cash:
            cash = {"free_cash_flow": _first(stored[0], "free_cash_flow")}

    currency = _text(profile, "currency", default=_text(metrics, "currency", default="USD"))
    revenue = _first(inc, "revenue", "total_revenue", "operating_revenue")
    revenue_prior = _first(prior, "revenue", "total_revenue", "operating_revenue")
    net_income = _first(inc, "bottom_line_net_income", "net_income")
    net_income_prior = _first(prior, "bottom_line_net_income", "net_income")
    gross_profit = _first(inc, "gross_profit")
    operating_income = _first(inc, "total_operating_income", "operating_income", "ebit")
    operating_income_prior = _first(prior, "total_operating_income", "operating_income", "ebit")
    ebitda = _first(inc, "ebitda")
    eps = _first(inc, "diluted_earnings_per_share", "basic_earnings_per_share")
    eps_prior = _first(prior, "diluted_earnings_per_share", "basic_earnings_per_share")
    cfo = _first(cash, "operating_cash_flow")
    fcf = _first(cash, "free_cash_flow")
    # Statement outflows are negative in the provider frames; keep the magnitudes
    # positive so capex intensity and the capital-allocation prose do not flip signs.
    capex = _outflow(
        _first(cash, "capital_expenditure", "purchase_of_property_plant_and_equipment")
    )
    capex_prior = _outflow(
        _first(
            data.cash[1] if len(data.cash) > 1 else {},
            "capital_expenditure",
            "purchase_of_property_plant_and_equipment",
        )
    )
    sbc = _first(cash, "stock_based_compensation")
    dividends_paid = _outflow(_first(cash, "net_dividends_paid", "common_dividends_paid"))
    buybacks = _outflow(_first(cash, "repurchase_of_common_equity"))
    working_capital = _first(cash, "change_in_working_capital")

    assets = _first(bal, "total_assets")
    debt = _first(bal, "total_debt", "long_term_debt")
    cash_balance = _first(bal, "cash_and_cash_equivalents", "cash_and_short_term_investments")
    equity = _first(bal, "total_common_equity", "total_equity_non_controlling_interests")
    current_assets = _first(bal, "total_current_assets")
    current_liabilities = _first(bal, "total_current_liabilities")

    price = _coalesce(
        _first(quote, "last_price"),
        _first(profile, "last_price"),
        _first(cons, "current_price"),
        _first(features, "current_price"),
    )
    market_cap = _coalesce(
        _first(profile, "market_cap"),
        _first(metrics, "market_cap"),
        _first(quote, "market_cap"),
    )
    analyst_target = _coalesce(
        _first(cons, "target_consensus"),
        _first(cons, "target_median"),
    )
    dcf_target = _first(dcf, "dcf")
    target = _coalesce(analyst_target, dcf_target)
    target_source = (
        "analyst consensus"
        if analyst_target is not None
        else "FMP DCF"
        if dcf_target is not None
        else "not available"
    )
    target_high = _first(cons, "target_high")
    target_low = _first(cons, "target_low")

    rev_growth = _growth(revenue, revenue_prior)
    eps_growth = _coalesce(_growth(eps, eps_prior), _growth(net_income, net_income_prior))
    gross_margin = _coalesce(
        _first(ratios, "gross_profit_margin"),
        _ratio(gross_profit, revenue),
        _first(features, "gross_margin"),
    )
    operating_margin = _coalesce(
        _first(ratios, "operating_profit_margin", "ebit_margin"),
        _ratio(operating_income, revenue),
        _first(features, "operating_margin"),
    )
    operating_margin_prior = _ratio(operating_income_prior, revenue_prior)
    net_margin = _coalesce(
        _first(ratios, "bottom_line_profit_margin", "net_profit_margin"),
        _ratio(net_income, revenue),
        _first(features, "net_margin"),
    )
    fcf_margin = _coalesce(_first(features, "fcf_margin"), _ratio(fcf, revenue))
    cash_conversion = _coalesce(_first(features, "cash_conversion"), _ratio(cfo, net_income))
    accrual_ratio = _ratio(None if net_income is None or cfo is None else net_income - cfo, assets)
    sbc_pct = _coalesce(
        _first(metrics, "stock_based_compensation_to_revenue"), _ratio(sbc, revenue)
    )
    net_debt = None if debt is None and cash_balance is None else (debt or 0) - (cash_balance or 0)
    net_debt_ebitda = _coalesce(
        _first(metrics, "net_debt_to_ebitda"),
        _ratio(net_debt, ebitda),
        _first(features, "net_debt_to_ebitda", "debt_to_ebitda"),
    )
    current_ratio = _coalesce(
        _first(ratios, "current_ratio", "quick_ratio"),
        _ratio(current_assets, current_liabilities),
        _first(metrics, "current_ratio"),
        _first(features, "current_ratio"),
    )
    debt_equity = _coalesce(
        _first(ratios, "debt_to_equity"),
        _ratio(debt, equity),
        _first(features, "debt_to_equity"),
    )
    pe = _coalesce(
        _first(ratios, "price_to_earnings"),
        _ratio(market_cap, net_income),
        _first(features, "pe_ratio"),
    )
    pb = _coalesce(
        _first(ratios, "price_to_book"),
        _ratio(market_cap, equity),
        _first(features, "price_to_book"),
    )
    ev_ebitda = _first(metrics, "ev_to_ebitda")
    earnings_yield = _coalesce(
        _first(metrics, "earnings_yield"),
        _ratio(1, pe),
        _first(features, "earnings_yield"),
    )
    fcf_yield = _coalesce(
        _first(metrics, "free_cash_flow_yield"),
        _ratio(fcf, market_cap),
        _first(features, "fcf_yield"),
    )
    profile_yield = _first(profile, "dividend_yield")
    if profile_yield is not None and data.providers.get("profile") == "yfinance":
        # yfinance reports the profile yield in percent; the ratios table is a fraction.
        profile_yield /= 100
    dividend_yield = _coalesce(
        _first(ratios, "dividend_yield"),
        _first(features, "dividend_yield"),
        _ratio(_first(profile, "annualized_dividend_amount"), price),
        profile_yield,
    )
    earnings_payout = _coalesce(
        _first(features, "earnings_payout"), _ratio_positive(dividends_paid, net_income)
    )
    fcf_payout = _coalesce(_first(features, "fcf_payout"), _ratio_positive(dividends_paid, fcf))
    dividend_coverage = _coalesce(
        _first(features, "dividend_coverage"), _ratio_positive(net_income, dividends_paid)
    )
    target_sustainable = _first(features, "target_sustainable_dividend")
    dividend_status = _dividend_verdict(
        dividends_paid, target_sustainable, dividend_coverage, fcf_payout
    )
    roe = _first(metrics, "return_on_equity")
    roic = _first(metrics, "return_on_invested_capital")
    beta = _first(profile, "beta")

    upside = _ratio(target, price)
    upside = None if upside is None else upside - 1
    target_multiple = _ratio(target, eps) if eps else None

    momentum = _coalesce(_momentum(data.prices), _first(features, "momentum_252d"))
    volatility = _coalesce(_volatility(data.prices), _first(features, "volatility_252d"))
    insider_buys, insider_sells = _insider_counts(data.insider, today)

    fy_revenue = None if revenue is None or rev_growth is None else revenue * (1 + rev_growth)
    next_fy_revenue = (
        None if fy_revenue is None or rev_growth is None else fy_revenue * (1 + rev_growth)
    )
    fy_eps = None if eps is None or eps_growth is None else eps * (1 + eps_growth)
    next_fy_eps = None if fy_eps is None or eps_growth is None else fy_eps * (1 + eps_growth)

    base_case = _coalesce(target, None if price is None else price * 1.05)
    bull_case = _coalesce(target_high, None if base_case is None else base_case * 1.15)
    bear_case = _coalesce(target_low, None if base_case is None else base_case * 0.85)
    base_return = _total_return(base_case, price, dividend_yield)
    bull_return = _total_return(bull_case, price, dividend_yield)
    bear_return = _total_return(bear_case, price, dividend_yield)
    expected_return = _weighted_return(base_return, bull_return, bear_return)

    analog_table, base_rate, analog_source = _analog(
        data.prices,
        today,
        warehouse.get("base_rate") or {},
        warehouse.get("own_returns") or [],
    )

    provider_summary = ", ".join(
        f"{name}: {provider}" for name, provider in sorted(data.providers.items())
    )
    if data.failures:
        provider_summary += f"; failed: {', '.join(sorted(data.failures))}"
    if warehouse:
        provider_summary += (
            "; warehouse: model.features, model.scores, raw.fmp_dcf, "
            "fundamentals.periodic_financials"
        )

    values = {
        "currency": currency,
        "name": _text(profile, "name", "long_name", default=data.ticker),
        "sector": _text(profile, "sector", default="not reported"),
        "industry": _text(profile, "industry_category", "industry", default="not reported"),
        "exchange": _text(profile, "stock_exchange", "exchange", default="not reported"),
        "country": _text(profile, "hq_country", "country", default="not reported"),
        "employees": _format_employees(_first(profile, "employees")),
        "description": _description(profile),
        "ceo": _text(profile, "ceo", default="not reported"),
        "peers_text": _peers_text(data.peers),
        "price": price,
        "market_cap": market_cap,
        "revenue": revenue,
        "rev_growth": rev_growth,
        "growth_word": "grew" if (rev_growth or 0) >= 0 else "fell",
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "fcf_margin": fcf_margin,
        "net_income": net_income,
        "eps": eps,
        "eps_growth": eps_growth,
        "ebitda": ebitda,
        "cfo": cfo,
        "fcf": fcf,
        "capex": capex,
        "capex_prior": capex_prior,
        "sbc": sbc,
        "dividends_paid": dividends_paid,
        "buybacks": buybacks,
        "working_capital": working_capital,
        "cash_conversion": cash_conversion,
        "accrual_ratio": accrual_ratio,
        "sbc_pct": sbc_pct,
        "net_debt_ebitda": net_debt_ebitda,
        "current_ratio": current_ratio,
        "debt_equity": debt_equity,
        "pe": pe,
        "pb": pb,
        "ev_ebitda": ev_ebitda,
        "earnings_yield": earnings_yield,
        "fcf_yield": fcf_yield,
        "dividend_yield": dividend_yield,
        "roe": roe,
        "roic": roic,
        "beta": beta,
        "target": target,
        "analyst_target": analyst_target,
        "target_source": target_source,
        "target_high": target_high,
        "target_low": target_low,
        "upside": upside,
        "target_multiple": target_multiple,
        "dcf": dcf_target,
        "dcf_as_of": dcf.get("as_of_date"),
        "dcf_margin": None if dcf_target is None or not price else dcf_target / price - 1,
        "earnings_payout": earnings_payout,
        "fcf_payout": fcf_payout,
        "dividend_coverage": dividend_coverage,
        "dividend_status": dividend_status,
        "interest_coverage": _first(features, "interest_coverage"),
        "refinancing_wall": _first(features, "refinancing_wall"),
        "target_sustainable_dividend": target_sustainable,
        "data_quality_score": _first(features, "data_quality_score"),
        "price_quality": _text(features, "price_quality", default="not reported"),
        "features_as_of": features.get("as_of_date"),
        "composite_score": _first(scores, "composite_score"),
        "sustainability_score": _first(scores, "sustainability_score"),
        "dividend_income_score": _first(scores, "dividend_income_score"),
        "appreciation_score": _first(scores, "appreciation_score"),
        "valuation_score": _first(scores, "valuation_score"),
        "score_coverage": _first(scores, "score_coverage"),
        "model_risk_score": _first(scores, "risk_score"),
        "cvs_tier": _text(scores, "cvs_tier", default=""),
        "market_regime": _text(scores, "market_regime", default=""),
        "credit_environment": _text(scores, "credit_environment", default=""),
        "scores_as_of": scores.get("as_of_date"),
        "evidence_ready": all(value is not None for value in (price, target, revenue, net_income)),
        "fy_revenue": fy_revenue,
        "next_fy_revenue": next_fy_revenue,
        "fy_eps": fy_eps,
        "next_fy_eps": next_fy_eps,
        "margin_trend": _margin_trend(operating_margin, operating_margin_prior),
        "profitability_trend": {
            "Expanding": "Improving",
            "Compressing": "Deteriorating",
            "Flat": "Stable",
        }[_margin_trend(operating_margin, operating_margin_prior)],
        "capital_discipline": _capital_discipline(fcf, capex, revenue, net_debt_ebitda),
        "barrier_sentence": _barrier_sentence(gross_margin, operating_margin),
        "quality_verdict": _quality_verdict(cash_conversion, accrual_ratio),
        "red_flags": _red_flags(cash_conversion, accrual_ratio, net_debt_ebitda, fcf),
        "moat": _moat(profile, gross_margin, operating_margin, roic, market_cap),
        "insider_buys": insider_buys,
        "insider_sells": insider_sells,
        "insider_signal": _insider_signal(insider_buys, insider_sells),
        "management_score": _management_score(
            roe, fcf, net_debt_ebitda, insider_buys, insider_sells
        ),
        "base_case": base_case,
        "bull_case": bull_case,
        "bear_case": bear_case,
        "base_return": base_return,
        "bull_return": bull_return,
        "bear_return": bear_return,
        "expected_return": expected_return,
        "analog_table": analog_table,
        "base_rate": base_rate,
        "analog_source": analog_source,
        "base_rate_detail": warehouse.get("base_rate") or {},
        "revision_trend": _revision_trend(data.price_target, today),
        "dispersion": _dispersion(target_high, target_low, target),
        "rich": bool((inc and bal and cash and data.ratios) or (features and (scores or stored))),
        "some": bool(inc or data.profile or features or stored),
        "source_short": (", ".join(sorted(set(data.providers.values()))) or "no provider")
        + (", warehouse" if warehouse else ""),
        "provider_summary": provider_summary,
    }
    values["risk"] = _risk(values, macro=macro, volatility=volatility)
    heuristic_risk = _risk_score(values["risk"])
    values["risk_score"] = (
        _clamp(1 + 9 * values["model_risk_score"])
        if values["model_risk_score"] is not None
        else heuristic_risk
    )
    values["risk_score_source"] = (
        "warehouse model" if values["model_risk_score"] is not None else "heuristic"
    )
    values["risk_word"] = (
        "high" if values["risk_score"] >= 7 else "moderate" if values["risk_score"] >= 4 else "low"
    )
    values["factors"] = _factors(
        values, macro=macro, momentum=momentum, volatility=volatility, beta=beta
    )
    values["recommendation"] = (
        _recommendation(expected_return, values["risk_score"]) if values["evidence_ready"] else ""
    )
    return values


# --- section heuristics ------------------------------------------------------------


def _num_or_na(value):
    return "N/A" if value is None else f"{value:,.2f}"


def _shift(value, amount):
    return None if value is None else value + amount


def _margin_trend(current, prior):
    if current is None or prior is None:
        return "Flat"
    if current - prior > 0.005:
        return "Expanding"
    if current - prior < -0.005:
        return "Compressing"
    return "Flat"


def _dividend_verdict(dividends_paid, target_sustainable, coverage, fcf_payout):
    if target_sustainable == 1:
        return "sustainable"
    if target_sustainable == 0:
        return "not sustainable"
    if not dividends_paid:
        return "not paid"
    if (coverage is not None and coverage < 1) or (fcf_payout is not None and fcf_payout > 1):
        return "at risk"
    if coverage is not None and coverage >= 1.5 and (fcf_payout is None or fcf_payout <= 0.8):
        return "covered"
    return "not proven"


def _dividend_phrase(c):
    status = c.get("dividend_status")
    if status == "not paid":
        return "no dividend was paid in the latest period"
    return f"the dividend is {status}"


def _dividend_summary(c):
    status = c.get("dividend_status")
    if status == "not paid":
        return " Dividend: no payment was reported in the latest period."
    details = []
    if c.get("dividend_yield") is not None:
        details.append(f"yield {_pct(c['dividend_yield'])}")
    if c.get("earnings_payout") is not None:
        details.append(f"earnings payout {_pct(c['earnings_payout'])}")
    if c.get("fcf_payout") is not None:
        details.append(f"FCF payout {_pct(c['fcf_payout'])}")
    if c.get("dividend_coverage") is not None:
        details.append(f"earnings cover {_x(c['dividend_coverage'])}")
    if not details:
        return " Dividend: the latest payment could not be related to earnings or free cash flow."
    source = (
        "stored model label"
        if c.get("target_sustainable_dividend") is not None
        else "data-derived view"
    )
    return f" Dividend: {', '.join(details)}; {source} says the dividend is {status}."


def _capital_discipline(fcf, capex, revenue, net_debt_ebitda):
    score = 6.0
    if fcf is not None:
        score += 1 if fcf > 0 else -1
    intensity = _ratio(capex, revenue)
    if intensity is not None:
        score += 1 if intensity < 0.1 else -1 if intensity > 0.25 else 0
    if net_debt_ebitda is not None:
        score += 1 if net_debt_ebitda < 1.5 else -1 if net_debt_ebitda > 3 else 0
    return _clamp(score)


def _barrier_sentence(gross_margin, operating_margin):
    if gross_margin is not None and gross_margin >= 0.45:
        return "High gross margins imply a meaningful barrier to entry."
    if gross_margin is not None and gross_margin < 0.15:
        return "Thin gross margins imply a low barrier to entry and price-led competition."
    return "Mid-range margins suggest a moderate barrier to entry."


def _quality_verdict(cash_conversion, accrual_ratio):
    if cash_conversion is None:
        return "Moderate"
    if cash_conversion >= 1.0 and (accrual_ratio is None or accrual_ratio < 0.05):
        return "High quality"
    if cash_conversion < 0.7 or (accrual_ratio is not None and accrual_ratio > 0.1):
        return "Low quality"
    return "Moderate"


def _red_flags(cash_conversion, accrual_ratio, net_debt_ebitda, fcf):
    flags = []
    if cash_conversion is not None and cash_conversion < 0.8:
        flags.append(f"cash conversion {_x(cash_conversion)} below 0.8")
    if accrual_ratio is not None and accrual_ratio > 0.08:
        flags.append(f"accruals {_pct(accrual_ratio)} of assets")
    if net_debt_ebitda is not None and net_debt_ebitda > 3:
        flags.append(f"net debt/EBITDA {_x(net_debt_ebitda)} above 3x")
    if fcf is not None and fcf < 0:
        flags.append("negative free cash flow")
    return "; ".join(flags) if flags else "No automatic red flag in the reported ratios."


def _moat(profile, gross_margin, operating_margin, roic, market_cap):
    sector = _text(profile, "sector").lower()
    strong_margins = gross_margin is not None and gross_margin >= 0.45
    scale = market_cap is not None and market_cap >= 10e9
    returns = roic is not None and roic >= 0.15
    if strong_margins and returns:
        rating = "Strong"
    elif (gross_margin or 0) >= 0.3 or returns:
        rating = "Moderate"
    elif (gross_margin or 0) >= 0.15:
        rating = "Weak"
    else:
        rating = "None"
    return {
        "network_effects": "Present"
        if sector in ("technology", "communication services")
        else "Absent",
        "scale_advantage": "Present" if scale and (gross_margin or 0) >= 0.3 else "Absent",
        "brand_strength": "Present" if strong_margins else "Absent",
        "switching_costs": "High"
        if strong_margins
        else "Moderate"
        if (gross_margin or 0) >= 0.25
        else "Low",
        "cost_leadership": "Present" if (operating_margin or 0) >= 0.2 else "Absent",
        "regulatory_advantage": "Present"
        if any(word in sector for word in ("utilities", "healthcare", "financial"))
        else "Absent",
        "moat_rating": rating,
        "durability_trend": "Stable",
    }


def _insider_counts(rows, today):
    buys = sells = 0
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=365)
    for row in rows or []:
        date = pd.to_datetime(row.get("transaction_date"), errors="coerce")
        if pd.isna(date) or date < cutoff:
            continue
        kind = str(
            row.get("transaction_type") or row.get("acquisition_or_disposition") or ""
        ).upper()
        if kind.startswith("P") or kind.startswith("A") or "BUY" in kind or "PURCHASE" in kind:
            buys += 1
        elif kind.startswith("S") or kind.startswith("D") or "SALE" in kind:
            sells += 1
    return buys, sells


def _insider_signal(buys, sells):
    if buys and sells:
        return "Buying" if buys > 2 * sells else "Selling" if sells > 2 * buys else "Mixed"
    if buys:
        return "Buying"
    if sells:
        return "Selling"
    return "None"


def _management_score(roe, fcf, net_debt_ebitda, buys, sells):
    score = 5.0
    if roe is not None:
        score += 1 if roe > 0.15 else -1 if roe < 0.05 else 0
    if fcf is not None:
        score += 1 if fcf > 0 else -1
    if net_debt_ebitda is not None and net_debt_ebitda > 3:
        score -= 1
    if buys > sells:
        score += 1
    elif sells > buys:
        score -= 1
    return _clamp(score)


def _weighted_return(base, bull, bear):
    values = [value for value in (base, bull, bear) if value is not None]
    if len(values) != 3:
        return base
    return 0.5 * base + 0.3 * bull + 0.2 * bear


def _recommendation(expected_return, risk_score):
    if expected_return is None:
        return "Hold"
    if expected_return >= 0.15 and risk_score <= 6:
        return "Buy"
    if expected_return >= 0.05:
        return "Add"
    if expected_return >= -0.05:
        return "Hold"
    if expected_return >= -0.15:
        return "Trim"
    return "Sell"


def _revision_trend(rows, today):
    dates = []
    for row in rows or []:
        date = pd.to_datetime(row.get("published_date"), errors="coerce")
        price = _num(row.get("price_target"))
        if not pd.isna(date) and price is not None:
            dates.append((date, price))
    if len(dates) < 2:
        return "Flat"
    dates.sort()
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=90)
    recent = [price for date, price in dates if date >= cutoff]
    older = [price for date, price in dates if date < cutoff]
    if not recent or not older:
        return "Flat"
    change = sum(recent) / len(recent) - sum(older) / len(older)
    reference = abs(sum(older) / len(older)) or 1.0
    if change / reference > 0.02:
        return "Upward"
    if change / reference < -0.02:
        return "Downward"
    return "Flat"


def _dispersion(high, low, target):
    if high is None or low is None or not target:
        return "Moderate"
    spread = (high - low) / abs(target)
    if spread > 0.5:
        return "High"
    if spread < 0.2:
        return "Low"
    return "Moderate"


def _sensitivity(c):
    revenue = c["revenue"]
    if not revenue:
        return None
    return 0.01 * revenue / (c["market_cap"] or revenue)


def _momentum(prices):
    """12M total return from adjusted closes (dividends reinvested)."""
    if len(prices) < 2:
        return None
    latest = prices[-1]
    year_ago = latest["date"] - pd.Timedelta(days=365)
    earlier = min(prices, key=lambda item: abs((item["date"] - year_ago).days))
    return _growth(latest["close"], earlier["close"])


def _volatility(prices):
    if len(prices) < 3:
        return None
    closes = pd.Series([item["close"] for item in prices])
    returns = closes.pct_change().dropna()
    if returns.empty:
        return None
    return float(returns.std() * math.sqrt(252))


def _peer_key_differences(c):
    """What differs between today's setup and the matched peer setups.

    The similarity filter conditions on yield and coverage only, so the honest
    answer names what it did not condition on: valuation and balance-sheet
    differences are the reader's to judge.
    """
    detail = c.get("base_rate_detail") or {}
    yield_now = detail.get("current_yield")
    coverage_now = detail.get("current_coverage")
    if yield_now is None or coverage_now is None:
        conditions = "The matched setups were chosen on dividend yield and coverage"
    else:
        conditions = (
            f"Today's setup is at a {yield_now * 100:.2f}% yield with "
            f"{coverage_now:.2f}x coverage; the matched setups are the peer group's "
            f"observations within 50% of both"
        )
    return (
        f"{conditions}. The peer sample does not condition on today's P/E of "
        f"{_x(c['pe'])} or free-cash-flow yield of {_pct(c['fcf_yield'])}, so those "
        f"are the variables to re-check, not just the total-return path."
    )


def _peer_implication(c):
    """What the peer base rate says, with the sample and the spread attached."""
    detail = c.get("base_rate_detail") or {}
    observations = detail.get("observations") or 0
    median = detail.get("median_return")
    p05 = detail.get("p05_return")
    p95 = detail.get("p95_return")
    peer_observations = detail.get("peer_observations") or 0
    peer_rate = detail.get("peer_pct_positive")
    industry = detail.get("industry") or "the peer group"

    parts = [
        f"{c['base_rate']:.0f}% of {observations} matched peer setups were positive over "
        f"the following twelve months"
    ]
    if median is not None:
        parts.append(f"median {median * 100:.1f}%")
    if p05 is not None and p95 is not None:
        parts.append(f"5th-95th percentile {p05 * 100:.1f}% to {p95 * 100:.1f}%")
    sentence = ", ".join(parts) + "."
    if peer_rate is not None and peer_observations:
        sentence += (
            f" The wider {industry} peer group was {peer_rate:.0f}% positive across "
            f"{peer_observations} observations."
        )
    return (
        f"{sentence} This is a descriptive rate over comparable setups in the period "
        f"covered, so it frames the position probabilistically rather than "
        f"predicting the next twelve months."
    )


def _peer_confidence_note(c):
    """The caveats, as the section's confidence note."""
    detail = c.get("base_rate_detail") or {}
    caveats = detail.get("caveats") or []
    observations = detail.get("observations") or 0
    prefix = (
        f"Peer base rate over {observations} matched observations, sampled monthly "
        f"from the stored forward-return table."
    )
    if caveats:
        return f"{prefix} " + " ".join(caveats)
    return prefix


def _analog(prices, today, base_rate=None, own_returns=None):
    """The analogs table, its base rate, and which of the two produced it.

    A peer base rate is preferred. "What happened to setups like this one" is
    answered by the sector's comparable setups, matched on the conditions that
    held at the time; the security's own twelve-month windows answer a different
    question -- "how has this one security gone", which is largely its own past
    and, over three windows, is a weak base rate. The own-history table is kept
    as the fallback for when the peer sample is missing or too thin.
    """
    if base_rate and base_rate.get("has_sample") and base_rate.get("similar_table"):
        rate = base_rate.get("pct_positive")
        if rate is not None:
            return base_rate["similar_table"], float(rate), "peer"
    if own_returns:
        table = analogs.own_history_table(own_returns)
        values = [
            row.get("total_return") for row in own_returns if row.get("total_return") is not None
        ]
        if values:
            rate = 100.0 * sum(1 for value in values if value > 0) / len(values)
            return table, rate, "own"
    table, rate = _own_history_analogs(prices, today)
    return table, rate, "own"


def _own_history_analogs(prices, today):
    """This security's own trailing twelve-month total-return windows.

    A fallback, not the answer: three overlapping windows of one security are
    not a base rate for a population, and the worksheet says so when it uses
    them.
    """
    header = (
        "| Period | Conditions | Forward 12M total return | Outcome |\n| --- | --- | --- | --- |"
    )
    rows, returns = [], []
    for offset in (3, 2, 1):
        end = pd.Timestamp(today) - pd.Timedelta(days=365 * (offset - 1))
        start = end - pd.Timedelta(days=365)
        start_close = _close_near(prices, start)
        end_close = _close_near(prices, end)
        if start_close is None or end_close is None:
            continue
        value = _growth(end_close, start_close)
        if value is None:
            continue
        returns.append(value)
        outcome = "Positive" if value >= 0 else "Negative"
        rows.append(
            f"| {start.date()} to {end.date()} | Same security, 12M total-return window | "
            f"{_pct(value)} | {outcome} |"
        )
    if not rows:
        return (
            "| Period | Conditions | Forward 12M total return | Outcome |\n"
            "| --- | --- | --- | --- |\n"
            "| not available | No price history was returned | N/A | Unknown |",
            0.0,
        )
    base_rate = 100.0 * sum(1 for value in returns if value > 0) / len(returns)
    return "\n".join([header, *rows]), base_rate


def _close_near(prices, when):
    if not prices:
        return None
    closest = min(prices, key=lambda item: abs((item["date"] - when).days))
    if abs((closest["date"] - when).days) > 60:
        return None
    return closest["close"]


def _risk(c, *, macro, volatility):
    hy = _macro_value(macro, "HY_OAS")
    sector = str(c.get("sector") or "").lower()
    current = _coalesce(c.get("current_ratio"), 1.0)
    net_debt = c.get("net_debt_ebitda")
    pe = c.get("pe")
    beta = c.get("beta")
    market_cap = c.get("market_cap")
    return {
        "business": "High"
        if (volatility is not None and volatility > 0.4) or (beta is not None and beta > 1.5)
        else "Low"
        if volatility is not None and volatility < 0.2
        else "Moderate",
        "valuation": "High"
        if (pe is not None and pe > 30)
        or (c.get("fcf_yield") is not None and c["fcf_yield"] < 0.02)
        else "Low"
        if pe is not None and pe < 15
        else "Moderate",
        "balance_sheet": "High"
        if (net_debt is not None and net_debt > 3) or current < 1
        else "Low"
        if net_debt is not None and net_debt < 1.5 and current >= 1.5
        else "Moderate",
        "macro": "High"
        if hy is not None and hy > 5.5
        else "Low"
        if hy is not None and hy < 3.5
        else "Moderate",
        "regulatory": "High"
        if any(word in sector for word in ("utilities", "healthcare", "energy"))
        else "Moderate",
        "liquidity": "High"
        if market_cap is not None and market_cap < 2e9
        else "Low"
        if market_cap is not None and market_cap > 10e9
        else "Moderate",
    }


def _risk_score(risk):
    points = {"Low": 1, "Moderate": 2, "High": 3}
    average = sum(points[value] for value in risk.values()) / len(risk)
    return _clamp(1 + (average - 1) / 2 * 9)


def _factors(c, *, macro, momentum, volatility, beta):
    hy = _macro_value(macro, "HY_OAS")
    return {
        "growth": "High"
        if (c.get("rev_growth") or 0) > 0.1
        else "Low"
        if c.get("rev_growth") is not None and c["rev_growth"] < 0
        else "Moderate",
        "value": "High"
        if (c.get("pe") is not None and c["pe"] < 15 and (c.get("pb") or 99) < 2)
        else "Low"
        if c.get("pe") is not None and c["pe"] > 30
        else "Moderate",
        "quality": "High"
        if (c.get("roe") or 0) > 0.15 and (c.get("cash_conversion") or 0) > 1
        else "Low"
        if c.get("roe") is not None and c["roe"] < 0.05
        else "Moderate",
        "momentum": "Positive"
        if momentum is not None and momentum > 0.02
        else "Negative"
        if momentum is not None and momentum < -0.02
        else "Neutral",
        "low_volatility": "Low"
        if volatility is not None and volatility < 0.2
        else "High"
        if volatility is not None and volatility > 0.4
        else "Moderate",
        "rate_duration": "High"
        if (c.get("debt_equity") or 0) > 1
        else "Low"
        if (c.get("net_debt_ebitda") or 0) < 1
        else "Moderate",
        "usd_exposure": "Low"
        if str(c.get("currency") or "").upper() == "USD"
        else "High"
        if hy is not None and hy > 5.5
        else "Moderate",
        "beta": beta,
    }


# --- formatting -------------------------------------------------------------------


def _format_employees(value):
    return "an unreported number of" if value is None else f"{int(value):,}"


def _description(profile):
    text = _text(profile, "long_description", "description")
    if not text:
        name = _text(profile, "name", default="The issuer")
        industry = _text(profile, "industry_category", "industry", default="its industry")
        return f"{name} operates in {industry}; no filed business description was returned."
    text = " ".join(text.split())
    return text if len(text) <= 600 else text[:597].rstrip() + "..."


def _peers_text(peers):
    names = []
    for row in peers or []:
        symbol = _text(row, "symbol")
        name = _text(row, "name")
        if symbol:
            names.append(f"{symbol} ({name})" if name else symbol)
    if not names:
        return "none returned"
    return ", ".join(names[:6])


def _sources(data):
    labels = {
        "profile": "company profile",
        "quote": "live quote",
        "consensus": "analyst consensus",
        "price_target": "analyst price targets",
        "ratios": "financial ratios",
        "metrics": "key metrics",
        "income": "income statement",
        "balance": "balance sheet",
        "cash": "cash-flow statement",
        "insider": "insider trades",
        "peers": "peer set",
        "prices": "price history",
    }
    parts = []
    for name, provider in data.providers.items():
        parts.append(f"{provider.upper()} {labels.get(name, name)}")
    return "Sources: " + "; ".join(sorted(parts)) + "." if parts else "Sources: none available."
