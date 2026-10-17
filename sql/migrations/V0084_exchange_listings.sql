-- Exchange-assigned security names from the Nasdaq Trader symbol directory.
--
-- Some active preferreds have no SEC cover-page title (raw.sec_instrument_titles),
-- so reference.securities.security_name stays the issuer name and the name parser
-- cannot extract a series, coupon or liquidation preference. On 2026-10-16, 53
-- such rows were visible in clean.ticker_profile. The free, keyless directory
-- (nasdaqtraded.txt) names every US-listed issue, NYSE preferreds included, and
-- covered 41 of the 53. Some of those titles also show the row is not a preferred
-- at all: Ford "6.20% Notes due June 1, 2059", NextEra "Junior Subordinated
-- Debentures", Seritage "Class A Common Stock".
-- scripts.populate_exchange_listing_titles snapshots the directory here and fills
-- only names that are still the issuer name; SEC cover titles always win.

CREATE TABLE IF NOT EXISTS raw.exchange_listings (
    symbol           text        PRIMARY KEY,
    security_name    text        NOT NULL,
    listing_exchange text,
    etf              boolean,
    test_issue       boolean,
    source_url       text        NOT NULL,
    retrieved_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.exchange_listings IS
  'Nasdaq Trader symbol directory snapshot (nasdaqtraded.txt): one row per listed '
  'symbol in the directory''s own form (AGM$I for preferred series I). Fallback '
  'security names for preferreds that have no SEC cover title.';
