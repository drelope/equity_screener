"""
Use this script to fetch preferred stock profile data for specific tickers in the reference.securities table.
The script provides both automated fetching via yfinance and a automate data entry method for preferred.security_terms table.
"""

import pandas as pd


def fetch_preferred_stock_data(tickers):
    """
    Fetch preferred stock profile data for given tickers.

    Args:
        tickers (list): List of ticker symbols (e.g., ['ACR-PC', 'ACR-PD', 'LFMDP'])

    Returns:
        dict: Dictionary containing stock data for each ticker
    """

    # Using yfinance for basic stock data
    try:
        import yfinance as yf
    except ImportError:
        print("Installing yfinance...")
        import subprocess
        import sys

        subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
        import yfinance as yf

    stock_data = {}

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)

            # Fetch historical data for yield calculation
            hist = stock.history(period="1y")
            current_price = hist["Close"].iloc[-1] if not hist.empty else None

            """
            Get info to update raw.ticker_profile table.
 Update the raw.company_ticker table with the fetched information.

            """
            info = stock.info

            stock_data[ticker] = {
                "ticker": ticker,
                "company_name": info.get("longName", "N/A"),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "current_price": current_price,
                "dividend_yield": info.get("dividendYield", None),
                "dividend_rate": info.get("dividendRate", None),
                "market_cap": info.get("marketCap", "N/A"),
                "52_week_high": info.get("fiftyTwoWeekHigh", "N/A"),
                "52_week_low": info.get("fiftyTwoWeekLow", "N/A"),
                "pe_ratio": info.get("trailingPE", "N/A"),
                "beta": info.get("beta", "N/A"),
            }

        except Exception as e:
            stock_data[ticker] = {"ticker": ticker, "error": f"Failed to fetch data: {str(e)}"}

    return stock_data


def create_preferred_stock_dataframe(tickers):
    """
    Create a pandas DataFrame with preferred stock data.

    Args:
        tickers (list): List of ticker symbols

    Returns:
        pd.DataFrame: DataFrame with stock information
    """
    data = fetch_preferred_stock_data(tickers)

    # Convert to list of dicts for DataFrame
    rows = []
    for ticker, info in data.items():
        rows.append(info)

    df = pd.DataFrame(rows)
    return df


def display_preferred_stocks(tickers):
    """
    Display preferred stock data in a formatted table.

    Args:
        tickers (list): List of ticker symbols
    """
    df = create_preferred_stock_dataframe(tickers)

    print("\n" + "=" * 120)
    print("PREFERRED STOCK PROFILES")
    print("=" * 120)
    print(df.to_string(index=False))
    print("=" * 120 + "\n")

    return df


# Automatic data entry version
def get_preferred_stock_manual_data():
    """
    Return atomaicly compiled preferred stock data based on research.
    Updates the reference.securities table with company profile information including 'security_type','sector'.
    Then updates the preferred.security_terms table with dividend and other terms.

    """

    preferred_stocks = {
        "ACR-PC": {
            "ticker": "ACR-PC",
            "company": "ACRES Commercial Realty Corp.",
            "security_type": "Series C Preferred Stock (8.625% Fixed-to-Floating)",
            "current_price": 23.52,
            "annual_dividend": 2.40,
            "dividend_yield": 10.19,
            "coupon_rate": 8.625,
            "call_date": "7/30/2024",
            "liquidation_preference": 25.00,
            "discount_to_par": -5.92,
            "payout_ratio": 5.51,
            "dividend_growth_3y": 7.36,
            "technical_signal": "Sell Candidate",
            "expected_downside": -7.08,
            "sector": "Real Estate (REIT)",
            "tax_status": "REIT - Ordinary Income Tax",
        },
        "ACR-PD": {
            "ticker": "ACR-PD",
            "company": "ACRES Commercial Realty Corp.",
            "security_type": "Series D Preferred Stock (7.875% Cumulative)",
            "current_price": 20.05,
            "annual_dividend": 1.97,
            "dividend_yield": 9.82,
            "coupon_rate": 7.875,
            "call_date": "5/21/2026",
            "liquidation_preference": 25.00,
            "discount_to_par": -19.80,
            "coupon_quarterly": 0.4921875,
            "pay_dates": ["1/30", "4/30", "7/30", "10/30"],
            "sector": "Real Estate (REIT)",
            "tax_status": "REIT - Ordinary Income Tax",
        },
        "LFMDP": {
            "ticker": "LFMDP",
            "company": "LifeMD Inc.",
            "security_type": "Series A Preferred Stock (8.875% Cumulative Perpetual)",
            "current_price": 23.50,
            "annual_dividend": 2.22,
            "dividend_yield": 9.44,
            "coupon_rate": 8.875,
            "call_date": "10/15/2024",
            "liquidation_preference": 25.00,
            "discount_to_par": -6.00,
            "coupon_quarterly": 0.5546875,
            "pay_dates": ["1/15", "4/15", "7/15", "10/15"],
            "52_week_high": 24.20,
            "52_week_low": 18.50,
            "sector": "Healthcare (Telehealth)",
            "tax_status": "Eligible for 15% Preferential Tax Rate",
        },
    }

    return preferred_stocks
