import logging
import re

import pandas as pd
from openbb import obb

from .config import settings

logger = logging.getLogger(__name__)


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


def dividends(symbol, start_date, end_date=None):
    kw = {"symbol": symbol, "start_date": start_date}
    if end_date:
        kw["end_date"] = end_date
    if settings.openbb_provider:
        kw["provider"] = settings.openbb_provider
    return _df(obb.equity.fundamental.dividends(**kw))


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
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance is not installed; %s will be missing quote fields", symbol)
        return data

    try:
        info = yf.Ticker(symbol).info
        for key, value in info.items():
            key = _norm_key(key)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                data.setdefault(key, value)
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        logger.warning("yfinance quote lookup failed for %s: %s", symbol, exc)

    return data
