import argparse

from src.crispdm.etl import load_dividends, load_prices

p = argparse.ArgumentParser()
p.add_argument("--symbols", required=True)
p.add_argument("--start", required=True)
p.add_argument("--end")
a = p.parse_args()
for t in [x.strip().upper() for x in a.symbols.split(",")]:
    print(t, "prices", load_prices(t, a.start, a.end))
    print(t, "dividends", load_dividends(t, a.start, a.end))
