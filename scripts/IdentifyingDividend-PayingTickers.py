"""Identify dividend-paying tickers from SEC company data via the maintained pipeline."""

from scripts.sec_dividend_analysis import build_dividend_dataset


def main():
    frame = build_dividend_dataset()
    payers = frame.loc[frame["pays_dividend"] == True]  # noqa: E712
    print(f"\nFinished identification. Found {len(payers)} dividend-paying tickers.")
    print(payers.to_string(index=False))
    payers.to_csv("identifying_dividend_paying_tickers.csv", index=False)


if __name__ == "__main__":
    main()
