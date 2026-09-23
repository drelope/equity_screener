"""Identify dividend-paying tickers from SEC company data."""

import requests
import json

# Your user email for SEC's fair access policy
user_email = "drelope@gmail.com"
headers = {"User-Agent": f"SampleApp {user_email}"}

# Fetch all company tickers
print("Fetching all company tickers from SEC...")
ticker_resp = requests.get('https://www.sec.gov/files/company_tickers.json', headers=headers)
ticker_resp.raise_for_status()
all_company_data = ticker_resp.json()

# Extract all tickers
all_tickers = [company['ticker'] for company in all_company_data.values()]
print(f"Found {len(all_tickers)} tickers in total.\n")

dividend_paying_tickers_info = []

print("--- Identify Dividend-Paying Tickers ---")
# Iterate through all tickers to identify dividend payers
for i, ticker in enumerate(all_tickers):
    if i % 100 == 0: # Print progress every 100 tickers
        print(f"Processing ticker {i}/{len(all_tickers)}: {ticker}")
    try:
        result = get_sec_data(ticker, user_email, lookback_years=2)
        if "error" in result:
            # print(f"  Error for {ticker}: {result['error']}") # Uncomment for verbose error logging
            pass
        elif result.get('Pays Dividend (recent)', False):
            dividend_paying_tickers_info.append(result)
    except requests.exceptions.RequestException as e:
        # print(f"  Network or API error for {ticker}: {e}") # Uncomment for verbose error logging
        pass
    except Exception as e:
        # print(f"  An unexpected error occurred for {ticker}: {e}") # Uncomment for verbose error logging
        pass

print(f"\nFinished identification. Found {len(dividend_paying_tickers_info)} dividend-paying tickers.\n")

print("--- Details for Identified Dividend-Paying Tickers ---")
if not dividend_paying_tickers_info:
    print("No dividend-paying tickers were identified.")
else:
    for info in dividend_paying_tickers_info:
        print(f"--- {info['Ticker']} ---")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print("\n")

print(f"Finished presenting details for {len(dividend_paying_tickers_info)} dividend-paying tickers.")