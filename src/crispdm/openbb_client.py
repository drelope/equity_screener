import json
import logging
import re
import time
from collections import Counter, deque
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import yfinance as yf
from openbb import obb

from .config import settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Keys read straight from the credentials file for services this client calls
#: without OpenBB (no OpenBB provider for them is installed).
DIRECT_KEYS = ("polygon_api_key",)
_direct_keys: dict[str, str] = {}


def load_credentials(path=None, credentials=None) -> list[str]:
    """Apply provider API keys from the credentials JSON to the OpenBB session.

    Only keys OpenBB defines are set (matched case-insensitively); of the rest, the
    ``DIRECT_KEYS`` this client uses itself are kept aside and others are ignored.
    Returns the names applied to OpenBB, never the values.
    """
    path = Path(path or settings.openbb_credentials_file)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("OpenBB credentials file %s is unreadable: %s", path, exc)
        return []
    values = payload.get("credentials", payload) if isinstance(payload, dict) else {}
    target = obb.user.credentials if credentials is None else credentials
    known = {name.lower(): name for name in type(target).model_fields}
    applied = []
    for key, value in values.items():
        name = known.get(str(key).lower())
        if name and isinstance(value, str) and value.strip():
            setattr(target, name, value.strip())
            applied.append(name)
        elif str(key).lower() in DIRECT_KEYS and isinstance(value, str) and value.strip():
            _direct_keys[str(key).lower()] = value.strip()
    if applied:
        logger.info("Loaded OpenBB credentials: %s", ", ".join(sorted(applied)))
    return sorted(applied)


load_credentials()


def _df(response):
    if hasattr(response, "to_dataframe"):
        return response.to_dataframe()
    if hasattr(response, "results"):
        vals = response.results
        return pd.DataFrame([x.model_dump() if hasattr(x, "model_dump") else x for x in vals])
    return pd.DataFrame(response)


def _norm_key(key):
    """Normalize profile keys to snake_case (e.g. exDividendDate -> ex_dividend_date)."""
    key = str(key).replace(" ", "_")
    key = re.sub(r"(?<!^)(?=[A-Z])", "_", key)
    return re.sub(r"_+", "_", key).lower().strip("_")


def historical_prices(symbol, start_date, end_date=None):
    kw = {"symbol": symbol, "start_date": start_date}
    if end_date:
        kw["end_date"] = end_date
    if settings.openbb_provider:
        kw["provider"] = settings.openbb_provider
    return _df(obb.equity.price.historical(**kw))


#: Dividend events are stored as provider OPENBB; the underlying OpenBB provider is
#: recorded per row in raw.dividend_data.feed. Order of preference (re-evaluated
#: 2026-10-16 once the FMP plan was upgraded): FMP returns the as-declared amount
#: (matching SEC 10-K declarations), real declaration/record/payment dates and
#: announced future ex-dates. Its adjusted amount is recomputed from Yahoo's split
#: factors so it matches the stored closes (see _price_basis_adjust); Yahoo Finance
#: (yfinance, no key needed) is the per-symbol fallback when FMP has nothing.
DIVIDEND_PROVIDERS = ("fmp", "yfinance")
DIVIDEND_PROVIDER = DIVIDEND_PROVIDERS[-1]

#: FMP allows 300 calls per rolling minute on the current plan, then answers 429
#: "Limit Reach" (measured 2026-10-16). Pace below it and wait out a 429 rather
#: than letting the symbol fall back to Yahoo for a transient reason.
FMP_CALLS_PER_MINUTE = 280
FMP_RATE_LIMIT_RETRIES = 3
FMP_DIVIDENDS_URL = "https://financialmodelingprep.com/stable/dividends"
_fmp_calls: deque = deque()

#: FMP field -> the OpenBB field name the loader normalises.
_FMP_FIELDS = {
    "date": "ex_dividend_date",
    "dividend": "amount",
    "adjDividend": "adjusted_amount",
    "recordDate": "record_date",
    "paymentDate": "payment_date",
    "declarationDate": "declaration_date",
    "frequency": "frequency",
}


def _fmp_key():
    credentials = getattr(getattr(obb, "user", None), "credentials", None)
    key = getattr(credentials, "fmp_api_key", None)
    if hasattr(key, "get_secret_value"):
        key = key.get_secret_value()
    return key or None


def _fmp_throttle(clock=time.monotonic, sleep=time.sleep):
    """Block until another FMP call fits in the rolling one-minute budget."""
    return _throttle(_fmp_calls, FMP_CALLS_PER_MINUTE, clock, sleep)


def _throttle(calls, per_minute, clock=time.monotonic, sleep=time.sleep):
    """Block until another call fits in a rolling one-minute budget of ``per_minute``."""
    now = clock()
    while calls and now - calls[0] >= 60:
        calls.popleft()
    if len(calls) >= per_minute:
        sleep(60 - (now - calls[0]) + 0.1)
        return _throttle(calls, per_minute, clock, sleep)
    calls.append(now)
    return None


def _is_rate_limited(exc) -> bool:
    message = str(exc)
    return "429" in message or "Limit Reach" in message


def _is_validation_error(exc) -> bool:
    message = str(exc)
    return "validation" in message.lower() or "Input should be a valid" in message


def _fmp_rest_dividends(symbol, start_date, end_date=None, opener=None):
    """FMP's dividend history read directly, for payloads OpenBB's model rejects.

    OpenBB's FMPHistoricalDividendsData refuses the empty strings FMP sends for a
    record, payment or declaration date that is not yet known (CAT, ASB-PF, ...), so
    the whole symbol fails. Read the same endpoint, treat blanks as missing, and
    return the frame OpenBB would have, with the same column names.
    """
    key = _fmp_key()
    if not key:
        return pd.DataFrame()
    url = f"{FMP_DIVIDENDS_URL}?{urlencode({'symbol': symbol, 'apikey': key})}"
    opener = opener or urlopen
    for attempt in range(FMP_RATE_LIMIT_RETRIES + 1):
        _fmp_throttle()
        try:
            with opener(url, timeout=30) as response:
                payload = json.load(response)
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == FMP_RATE_LIMIT_RETRIES:
                raise RuntimeError(f"FMP dividends HTTP {exc.code} for {symbol}") from None
            time.sleep(60)
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()
    frame = pd.DataFrame(payload).rename(columns=_FMP_FIELDS)
    frame = frame[[c for c in _FMP_FIELDS.values() if c in frame.columns]]
    frame = frame.replace({"": None})
    ex_dates = pd.to_datetime(frame["ex_dividend_date"], errors="coerce")
    keep = ex_dates >= pd.Timestamp(start_date)
    if end_date:
        keep &= ex_dates <= pd.Timestamp(end_date)
    return frame[keep].reset_index(drop=True)


def _fmp_dividends(symbol, start_date, end_date=None):
    """FMP through OpenBB, paced, retried on 429, read directly on a model error."""
    kw = {"symbol": symbol, "start_date": start_date, "provider": "fmp"}
    if end_date:
        kw["end_date"] = end_date
    for attempt in range(FMP_RATE_LIMIT_RETRIES + 1):
        _fmp_throttle()
        try:
            return _df(obb.equity.fundamental.dividends(**kw))
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_validation_error(exc):
                logger.debug(
                    "FMP payload for %s failed OpenBB validation; reading it directly", symbol
                )
                return _fmp_rest_dividends(symbol, start_date, end_date)
            if not _is_rate_limited(exc) or attempt == FMP_RATE_LIMIT_RETRIES:
                raise
            logger.info("FMP rate limit reached at %s; waiting a minute", symbol)
            time.sleep(60)
    return pd.DataFrame()


def _yahoo_history(symbol):
    """Yahoo's split factors ({date: ratio}) and dividends ([(date, amount)]).

    Both come from one Yahoo request. Returns (None, None) when Yahoo has no
    history for the symbol, so the caller keeps FMP's figures unchanged.
    """
    try:
        ticker = yf.Ticker(symbol)
        splits = ticker.splits
        paid = ticker.dividends
    except Exception as exc:  # noqa: BLE001 - adjustment falls back to FMP's own
        logger.debug("Yahoo history unavailable for %s: %s", symbol, exc)
        return None, None
    if splits is None or paid is None:
        return None, None
    splits = {pd.Timestamp(k).date(): float(v) for k, v in splits.items() if float(v) > 0}
    paid = [(pd.Timestamp(k).date(), float(v)) for k, v in paid.items() if float(v) > 0]
    return splits, paid


def _later_factor(splits, ex_date) -> float:
    factor = 1.0
    for split_date, ratio in (splits or {}).items():
        if split_date > ex_date:
            factor *= ratio
    return factor


def _price_basis_adjust(frame, splits):
    """Restate FMP's per-share amounts on the basis of the stored closes.

    The closes come from Yahoo and are restated by Yahoo's split factors, which
    also cover spin-offs Yahoo books as splits (CTVA 6.665) and small stock
    dividends (TROLB 1.03). FMP's adjDividend does not follow them (SF stays 0.46
    after its 3-for-2; GPMT is not restated for its 1-for-10), so a feature built
    from it would see a fake raise or cut. Dividing the declared amount by every
    later factor puts the payment on the same basis as the close it is compared
    with. Without a split history FMP's own figure is kept.
    """
    if splits is None or frame.empty or "amount" not in frame.columns:
        return frame
    ex_dates = pd.to_datetime(frame["ex_dividend_date"], errors="coerce").dt.date
    amounts = pd.to_numeric(frame["amount"], errors="coerce")
    adjusted = []
    for ex_date, amount in zip(ex_dates, amounts):
        if pd.isna(amount) or ex_date is None or pd.isna(ex_date):
            adjusted.append(None)
            continue
        adjusted.append(amount / _later_factor(splits, ex_date))
    frame = frame.copy()
    frame["adjusted_amount"] = adjusted
    return frame


#: Polygon.io (free key: 5 calls per minute) settles an amount FMP and Yahoo
#: disagree on. Its cash_amount is the as-declared figure in the stated currency.
POLYGON_DIVIDENDS_URL = "https://api.polygon.io/v3/reference/dividends"
POLYGON_CALLS_PER_MINUTE = 5
_polygon_calls: deque = deque()

#: Two feeds agree on an event within 1%, or within Yahoo's 3-decimal rounding.
AMOUNT_TOLERANCE = 0.01
YAHOO_ROUNDING = 0.0005
#: Feeds date the same payment up to a few days apart (GFIOF: 2 days).
EVENT_WINDOW_DAYS = 4
#: A feed is confirmed by Polygon when it is within 10% of Polygon's figure (ADR
#: amounts move with the FX rate and depositary fee on the conversion date) and
#: at most half as far from it as the other feed.
POLYGON_MAX_ERROR = 0.10


def _polygon_key():
    key = _direct_keys.get("polygon_api_key")
    if not key:
        credentials = getattr(getattr(obb, "user", None), "credentials", None)
        key = getattr(credentials, "polygon_api_key", None)
        if hasattr(key, "get_secret_value"):
            key = key.get_secret_value()
    return key or None


def polygon_dividends(symbol, start_date, opener=None):
    """Polygon's dividend events since ``start_date`` as [(ex_date, amount, currency)].

    Returns None when no key is configured or Polygon cannot be read, so the
    caller can tell "no evidence" from "no events".
    """
    key = _polygon_key()
    if not key:
        return None
    query = {
        "ticker": symbol.replace("-", "."),
        "ex_dividend_date.gte": str(start_date),
        "limit": 1000,
        "apiKey": key,
    }
    url = f"{POLYGON_DIVIDENDS_URL}?{urlencode(query)}"
    opener = opener or urlopen
    for attempt in range(FMP_RATE_LIMIT_RETRIES + 1):
        _throttle(_polygon_calls, POLYGON_CALLS_PER_MINUTE)
        try:
            with opener(url, timeout=30) as response:
                payload = json.load(response)
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == FMP_RATE_LIMIT_RETRIES:
                logger.debug("Polygon dividends HTTP %s for %s", exc.code, symbol)
                return None
            time.sleep(60)
        except OSError as exc:
            logger.debug("Polygon dividends unreachable for %s: %s", symbol, exc)
            return None
    events = {}
    for row in payload.get("results") or []:
        ex = pd.to_datetime(row.get("ex_dividend_date"), errors="coerce")
        amount = row.get("cash_amount")
        if pd.isna(ex) or not amount:
            continue
        # A regular and a supplemental dividend on one ex-date (HTGC 0.40 + 0.07) are
        # one payment in Yahoo's and FMP's lists.
        key = (ex.date(), str(row.get("currency") or "").upper())
        events[key] = events.get(key, 0.0) + float(amount)
    return [(ex, amount, currency) for (ex, currency), amount in events.items()]


def _closest(candidates, ex_date, targets):
    """The candidate event nearest in amount to any target, then in date."""
    near = [c for c in candidates if abs((c[0] - ex_date).days) <= EVENT_WINDOW_DAYS]
    if not near:
        return None
    return min(
        near, key=lambda c: (min(abs(c[1] - t) for t in targets), abs((c[0] - ex_date).days))
    )


def _agree(a, b) -> bool:
    return abs(a - b) <= max(AMOUNT_TOLERANCE * max(abs(a), abs(b)), YAHOO_ROUNDING + 1e-12)


def _verdict(fmp_amount, yahoo_amount, polygon_amount) -> str:
    fmp_error = abs(fmp_amount - polygon_amount) / polygon_amount
    yahoo_error = abs(yahoo_amount - polygon_amount) / polygon_amount
    if yahoo_error <= POLYGON_MAX_ERROR and 2 * yahoo_error < fmp_error:
        return "yfinance"
    if fmp_error <= POLYGON_MAX_ERROR and fmp_error <= yahoo_error:
        return "fmp"
    return "unresolved"


def reconcile_amounts(frame, yahoo, splits, polygon, checks=None):
    """Settle FMP amounts that Yahoo contradicts, using Polygon as the tiebreaker.

    No feed is right every time. Of 165 events where FMP and Yahoo differed by more
    than 1% (2026-10-16), Polygon matched FMP on 114 (TSM, IHG, UL, Canadian OTC
    listings Yahoo converts at a stale FX rate) and Yahoo on 22 (CHA, whose 6-K
    declares US$0.92 where FMP has 0.87; SAN, EQNR, HTGC), and was within a few
    percent of Yahoo where FMP was far off on ORANY, ABBNY, FORTY and IMOS.

    For each FMP event Yahoo also lists (within ``EVENT_WINDOW_DAYS``, compared on
    the split-restated basis), a disagreement is looked up in ``checks`` (earlier
    verdicts keyed by ex-date) or else in Polygon (``polygon`` is called at most
    once and returns USD and other-currency events, or None). When Polygon
    confirms Yahoo, Yahoo's amount replaces FMP's, restated to the declared basis,
    and ``amount_feed`` says so. Otherwise FMP's figure stays.

    Returns the frame and the new verdicts, as dicts the loader can store.
    """
    frame = frame.copy()
    frame["amount_feed"] = "fmp"
    if yahoo is None or splits is None or frame.empty:
        return frame, []
    checks = checks or {}
    polygon_events = None
    polygon_asked = False
    new_checks = []
    ex_dates = pd.to_datetime(frame["ex_dividend_date"], errors="coerce").dt.date
    pairs = []
    for index, ex_date in zip(frame.index, ex_dates):
        amount = pd.to_numeric(frame.at[index, "amount"], errors="coerce")
        if pd.isna(amount) or ex_date is None or pd.isna(ex_date):
            continue
        factor = _later_factor(splits, ex_date)
        pairs.append((index, ex_date, amount, factor, _closest(yahoo, ex_date, [amount / factor])))
    # One Yahoo payment claimed by several FMP events (CMBT: FMP 0.44 + 0.20 on
    # consecutive days, Yahoo 0.64) is FMP listing it in parts; copying Yahoo's
    # figure onto each part would count it twice.
    claims = Counter(match for *_, match in pairs if match is not None)
    for index, ex_date, amount, factor, match in pairs:
        if match is None or claims[match] > 1 or _agree(amount / factor, match[1]):
            continue
        fmp_amount, yahoo_amount = float(amount), match[1] * factor

        cached = checks.get(ex_date)
        if (
            cached
            and _agree(float(cached["fmp_amount"]), fmp_amount)
            and _agree(float(cached["yahoo_amount"]), yahoo_amount)
        ):
            chosen = cached["chosen"]
        else:
            if not polygon_asked:
                polygon_events, polygon_asked = polygon(), True
            usd = [e for e in polygon_events or [] if e[2] in ("USD", "")]
            found = _closest(usd, ex_date, [fmp_amount, yahoo_amount])
            other = _closest(polygon_events or [], ex_date, [fmp_amount, yahoo_amount])
            chosen = _verdict(fmp_amount, yahoo_amount, found[1]) if found else "unresolved"
            new_checks.append(
                {
                    "ex_dividend_date": ex_date,
                    "fmp_amount": fmp_amount,
                    "yahoo_amount": yahoo_amount,
                    "polygon_amount": (found or other or (None, None))[1],
                    "polygon_currency": (found or other or (None, None, None))[2],
                    "chosen": chosen,
                }
            )
        if chosen == "yfinance":
            frame.at[index, "amount"] = yahoo_amount
            frame.at[index, "adjusted_amount"] = match[1]
            frame.at[index, "amount_feed"] = "yfinance"
    return frame, new_checks


def dividend_providers() -> tuple[str, ...]:
    """Providers to try, in order. An explicit OPENBB_PROVIDER pins a single one."""
    if settings.openbb_provider:
        return (settings.openbb_provider,)
    credentials = getattr(getattr(obb, "user", None), "credentials", None)
    has_fmp_key = bool(getattr(credentials, "fmp_api_key", None))
    return DIVIDEND_PROVIDERS if has_fmp_key else (DIVIDEND_PROVIDER,)


def dividends(symbol, start_date, end_date=None, amount_checks=None):
    """Dividend events for one symbol from the first provider that returns any.

    The provider that answered is attached as ``frame.attrs["feed"]`` so the loader
    can record provenance. FMP amounts are restated to the closes' split basis and
    reconciled with Yahoo (``reconcile_amounts``); ``amount_checks`` holds earlier
    verdicts for this symbol by ex-date, and new ones are returned in
    ``frame.attrs["amount_checks"]``. When every provider fails, the last error is
    raised.
    """
    last_error = None
    answered = False
    frame = pd.DataFrame()
    for provider in dividend_providers():
        kw = {"symbol": symbol, "start_date": start_date, "provider": provider}
        if end_date:
            kw["end_date"] = end_date
        try:
            if provider == "fmp":
                frame = _fmp_dividends(symbol, start_date, end_date)
            else:
                frame = _df(obb.equity.fundamental.dividends(**kw))
        except Exception as exc:  # noqa: BLE001 - try the next provider
            last_error = exc
            logger.debug("%s dividends failed for %s: %s", provider, symbol, exc)
            continue
        answered = True
        if frame is not None and not frame.empty:
            checks = []
            if provider == "fmp":
                splits, paid = _yahoo_history(symbol)
                frame = _price_basis_adjust(frame, splits)
                first = pd.to_datetime(frame["ex_dividend_date"], errors="coerce").min()
                since = (first - pd.Timedelta(days=EVENT_WINDOW_DAYS)).date()
                frame, checks = reconcile_amounts(
                    frame,
                    paid,
                    splits,
                    lambda: polygon_dividends(symbol, since),
                    amount_checks,
                )
            frame.attrs["feed"] = provider
            frame.attrs["amount_checks"] = checks
            return frame
    if not answered and last_error is not None:
        raise last_error
    return pd.DataFrame() if frame is None else frame


def profile(symbol):
    """Return OpenBB company profile data for a ticker symbol."""
    kw = {"symbol": symbol}
    if settings.openbb_provider:
        kw["provider"] = settings.openbb_provider
    return _df(obb.equity.profile(**kw))


def stock_summary(symbol):
    """Return a merged company profile / quote summary dict for a ticker symbol.

    Pulls the structured company profile through OpenBB's yfinance provider
    and fills any remaining fields (dividend rate, yields, latest price, ...)
    from the yfinance quote info. Keys are lower-cased with spaces replaced
    by underscores so they can be mapped directly onto storage columns.
    """
    data = {}

    try:
        frame = profile(symbol)
        if frame is not None and not frame.empty:
            for key, value in frame.iloc[0].to_dict().items():
                key = _norm_key(key)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    data.setdefault(key, value)
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        logger.warning("OpenBB profile lookup failed for %s: %s", symbol, exc)

    try:
        info = yf.Ticker(symbol).info
        for key, value in info.items():
            key = _norm_key(key)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                data.setdefault(key, value)
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        logger.warning("yfinance quote lookup failed for %s: %s", symbol, exc)

    return data


#: FMP financial statement types mapped to the OpenBB command path returning each.
FMP_STATEMENT_COMMANDS = {
    "income": ("equity", "fundamental", "income"),
    "balance": ("equity", "fundamental", "balance"),
    "cash": ("equity", "fundamental", "cash"),
}

#: FMP's discounted-cash-flow endpoint. OpenBB 4.7.2 exposes no DCF command in any
#: provider, so the estimate is read directly, the same pattern as
#: ``_fmp_rest_dividends``.
FMP_DCF_URL = "https://financialmodelingprep.com/stable/discounted-cash-flow"


def _has_fmp_key():
    """True when an FMP key is loaded on the OpenBB session."""
    return bool(_fmp_key())


def _fmp_provider():
    """The provider to pin for an explicit FMP call; an explicit setting still wins."""
    return settings.openbb_provider or "fmp"


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def financial_statements(symbol, statement="income", limit=None):
    """Reported income, balance-sheet or cash-flow statement from FMP.

    ``statement`` is one of ``income``, ``balance`` or ``cash`` (the keys of
    ``FMP_STATEMENT_COMMANDS``). Returns one row per fiscal period with FMP's
    snake_case column names. Each call is paced by ``_fmp_throttle`` so a
    full-universe run stays under FMP's per-minute budget.
    """
    try:
        path = FMP_STATEMENT_COMMANDS[statement]
    except KeyError:
        raise ValueError(
            f"unknown FMP statement {statement!r}; expected one of {sorted(FMP_STATEMENT_COMMANDS)}"
        ) from None
    target = obb
    for part in path:
        target = getattr(target, part)
    kw = {"symbol": symbol, "provider": _fmp_provider()}
    if limit:
        kw["limit"] = limit
    _fmp_throttle()
    return _df(target(**kw))


def statement_key(row):
    """The ``raw.fmp_statements`` key of one FMP statement row, or None when unkeyable.

    Returns ``(period_end, fiscal_period, fiscal_year, filing_date)``: the date the
    period ended, FMP's fiscal label, the fiscal year (None when unparseable) and the
    date FMP accepted the filing. The ETL upsert and the API's live fallback both key
    with this, so a live read is shaped exactly like a stored row.
    """
    period_end = pd.to_datetime(row.get("period_ending"), errors="coerce")
    filing_date = pd.to_datetime(row.get("filing_date"), errors="coerce")
    if pd.isna(period_end) or pd.isna(filing_date):
        return None
    try:
        fiscal_year = int(row.get("fiscal_year"))
    except (TypeError, ValueError):
        fiscal_year = None
    return (
        period_end.date(),
        str(row.get("fiscal_period") or ""),
        fiscal_year,
        filing_date.date(),
    )


def discounted_cash_flow(symbol, opener=None):
    """FMP's own discounted-cash-flow estimate for one symbol.

    OpenBB 4.7.2 has no DCF command in any provider, so the estimate is read from
    FMP directly, paced and retried on a 429 like ``_fmp_rest_dividends``. Returns
    a dict with ``as_of_date``, ``dcf``, ``stock_price`` and ``reported_currency``,
    or None when no FMP key is configured or FMP cannot be read, so a caller can
    tell "no estimate" from "no key".
    """
    key = _fmp_key()
    if not key:
        return None
    url = f"{FMP_DCF_URL}?{urlencode({'symbol': symbol, 'apikey': key})}"
    opener = opener or urlopen
    payload = None
    for attempt in range(FMP_RATE_LIMIT_RETRIES + 1):
        _fmp_throttle()
        try:
            with opener(url, timeout=30) as response:
                payload = json.load(response)
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == FMP_RATE_LIMIT_RETRIES:
                logger.debug("FMP DCF HTTP %s for %s", exc.code, symbol)
                return None
            time.sleep(60)
        except OSError as exc:
            logger.debug("FMP DCF unreachable for %s: %s", symbol, exc)
            return None
    if not isinstance(payload, (list, dict)):
        return None
    rows = payload if isinstance(payload, list) else [payload]
    row = rows[0] if rows else {}
    as_of = pd.to_datetime(row.get("date"), errors="coerce")
    return {
        "as_of_date": None if pd.isna(as_of) else as_of.date(),
        "dcf": _number(row.get("dcf")),
        "stock_price": _number(row.get("Stock Price", row.get("stock_price"))),
        "reported_currency": row.get("reported_currency") or row.get("currency"),
    }


def filings(symbol, limit=None):
    """FMP's company filings for one symbol.

    A second SEC-filings source alongside the direct SEC submissions already stored
    in ``raw.sec_submissions``; the ``provider`` column records which one answered.
    Returns FMP's columns (``filing_date``, ``report_type``, ``report_url``,
    ``filing_url``, ``accepted_date``).
    """
    kw = {"symbol": symbol, "provider": _fmp_provider()}
    if limit:
        kw["limit"] = limit
    _fmp_throttle()
    return _df(obb.equity.fundamental.filings(**kw))
