import uuid

import pandas as pd
from sqlalchemy import text

from .db import engine
from .openbb_client import dividends, historical_prices


def ensure_security(ticker, security_type="common_stock"):
    ticker = ticker.upper()
    security_type = security_type.lower()
    with engine.begin() as c:
        existing = c.execute(
            text("""
          SELECT security_id
          FROM reference.securities
          WHERE ticker = :ticker
          ORDER BY active DESC, created_at
          LIMIT 1
        """),
            {"ticker": ticker},
        ).scalar()
        if existing:
            return existing

        cik = c.execute(
            text("""
          SELECT cik FROM raw.company_ticker WHERE ticker = :ticker
        """),
            {"ticker": ticker},
        ).scalar()
        if cik is None:
            raise ValueError(f"Ticker {ticker} is not present in raw.company_ticker")

        sid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"dividend-equity:{ticker}:{cik}:{security_type}:false",
        )
        c.execute(
            text("""
            INSERT INTO reference.securities
            (security_id,ticker,cik,security_name,security_type,dividend,
             sec_data_status)
            VALUES (:sid,:ticker,:cik,:ticker,:stype,false,'unavailable')
            ON CONFLICT (security_id) DO UPDATE SET updated_at=now()
          """),
            {"sid": sid, "ticker": ticker, "cik": cik, "stype": security_type},
        )
        return sid


def load_prices(ticker, start, end=None):
    sid = ensure_security(ticker)
    df = historical_prices(ticker, start, end)
    if df.empty:
        return 0
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    date_col = "date" if "date" in df.columns else "datetime"
    with engine.begin() as c:
        for _, r in df.iterrows():
            c.execute(
                text("""
              INSERT INTO raw.market_data
              (security_id,observation_date,open,high,low,close,adjusted_close,volume,provider)
              VALUES (:sid,:dt,:o,:h,:l,:c,:a,:v,'openbb')
              ON CONFLICT DO NOTHING
            """),
                {
                    "sid": sid,
                    "dt": pd.to_datetime(r[date_col]).date(),
                    "o": r.get("open"),
                    "h": r.get("high"),
                    "l": r.get("low"),
                    "c": r.get("close"),
                    "a": r.get("adj_close", r.get("adjusted_close")),
                    "v": r.get("volume"),
                },
            )
    return len(df)


def load_dividends(ticker, start, end=None):
    sid = ensure_security(ticker)
    df = dividends(ticker, start, end)
    if df.empty:
        return 0
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    with engine.begin() as c:
        for _, r in df.iterrows():

            def d(name):
                return pd.to_datetime(r[name]).date() if name in r and pd.notna(r[name]) else None

            c.execute(
                text("""
              INSERT INTO raw.dividend_data
              (security_id,ex_dividend_date,declaration_date,record_date,payment_date,
               amount,adjusted_amount,frequency,currency,provider)
              VALUES (:sid,:ex,:decl,:rec,:pay,:amt,:adj,:freq,:cur,'openbb')
              ON CONFLICT DO NOTHING
            """),
                {
                    "sid": sid,
                    "ex": d("ex_dividend_date"),
                    "decl": d("declaration_date"),
                    "rec": d("record_date"),
                    "pay": d("payment_date"),
                    "amt": r.get("amount"),
                    "adj": r.get("adjusted_amount"),
                    "freq": r.get("frequency"),
                    "cur": r.get("currency", "USD"),
                },
            )
    return len(df)
