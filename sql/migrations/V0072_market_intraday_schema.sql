-- =====================================================================
-- V0072: reserve the market schema for intraday market data.
--
-- The market schema has existed since the baseline (see sql/schema.sql)
-- but has never held a table. The pipeline is nightly-batch: daily OHLCV
-- lands in raw.market_data and docs/requirements.md section 6 puts
-- "Intraday/real-time data" and "Broker integration or live order
-- execution" explicitly out of scope for the MVP.
--
-- This migration does not add an acquisition path. It declares the
-- structured shapes intraday data would land in so the schema is reserved
-- and reviewed now, and so a later source can be wired in without an
-- architectural change. The tables stay empty until such a source exists.
--
-- Design notes:
--
--   * Each table is declaratively RANGE-partitioned by month on ts, so
--     retention is a partition DROP rather than a DELETE of millions of
--     rows, and time-window queries prune to the partitions they touch.
--   * A DEFAULT partition makes each table writable before any monthly
--     partition exists. A future loader must create the month's partition
--     and drain rows the default already holds before attaching it
--     (PostgreSQL refuses to attach a partition whose bounds overlap
--     rows already present in the default). This is the standard
--     partitioned-table bootstrap and is documented here so the
--     constraint is not rediscovered at ingestion time.
--   * Intraday prices and sizes are DOUBLE PRECISION, not NUMERIC. The
--     daily raw.market_data keeps exact NUMERIC because it is the source
--     of record for returns and dividends. Tick, quote and bar values are
--     research and execution inputs where fixed-width compact storage and
--     scan speed dominate and sub-cent exactness is not required; a
--     float8 matches the wire format of every market-data feed.
--   * Every primary key includes ts because a partitioned table's key must
--     contain the partition key. market.trade additionally carries a
--     bigint identity: real feeds print several trades at the same
--     microsecond, so (security_id, ts) is not unique there. quote and bar
--     take their natural grain in the key instead.
--   * security_id is a UUID foreign key into reference.securities, the
--     same identity the daily pipeline uses, so intraday joins to the rest
--     of the warehouse without a translation layer.
--   * BRIN on ts is the retention/time-scan index: it is tiny next to a
--     btree and effective because rows arrive in ts order. A btree on
--     (security_id, ts) serves the per-security slice.
--
-- Idempotent; the same statements are declared in sql/schema.sql so a
-- fresh build and this migration converge.
-- =====================================================================

CREATE TABLE IF NOT EXISTS market.trade (
  trade_id BIGINT GENERATED ALWAYS AS IDENTITY,
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  ts TIMESTAMPTZ NOT NULL,
  price DOUBLE PRECISION NOT NULL,
  size BIGINT,
  exchange VARCHAR(16),
  conditions TEXT[],
  provider VARCHAR(64) NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (trade_id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS market.quote (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  ts TIMESTAMPTZ NOT NULL,
  bid DOUBLE PRECISION,
  ask DOUBLE PRECISION,
  bid_size BIGINT,
  ask_size BIGINT,
  exchange VARCHAR(16),
  provider VARCHAR(64) NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, ts, provider)
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS market.bar (
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  interval VARCHAR(16) NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  open DOUBLE PRECISION,
  high DOUBLE PRECISION,
  low DOUBLE PRECISION,
  close DOUBLE PRECISION,
  volume BIGINT,
  provider VARCHAR(64) NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, interval, ts, provider)
) PARTITION BY RANGE (ts);

CREATE TABLE IF NOT EXISTS market.trade_default PARTITION OF market.trade DEFAULT;
CREATE TABLE IF NOT EXISTS market.quote_default PARTITION OF market.quote DEFAULT;
CREATE TABLE IF NOT EXISTS market.bar_default PARTITION OF market.bar DEFAULT;

CREATE INDEX IF NOT EXISTS ix_market_trade_security_ts
  ON market.trade (security_id, ts);
CREATE INDEX IF NOT EXISTS ix_market_trade_ts_brin
  ON market.trade USING brin (ts);

CREATE INDEX IF NOT EXISTS ix_market_quote_security_ts
  ON market.quote (security_id, ts);
CREATE INDEX IF NOT EXISTS ix_market_quote_ts_brin
  ON market.quote USING brin (ts);

CREATE INDEX IF NOT EXISTS ix_market_bar_security_interval_ts
  ON market.bar (security_id, interval, ts);
CREATE INDEX IF NOT EXISTS ix_market_bar_ts_brin
  ON market.bar USING brin (ts);

COMMENT ON TABLE market.trade IS
  'RESERVED intraday trade prints, month-partitioned on ts. Empty: no acquisition '
  'path exists (intraday data is out of scope for the MVP).';
COMMENT ON TABLE market.quote IS
  'RESERVED intraday top-of-book quotes, month-partitioned on ts. Empty: no '
  'acquisition path exists (intraday data is out of scope for the MVP).';
COMMENT ON TABLE market.bar IS
  'RESERVED intraday OHLCV bars, month-partitioned on ts. Empty: no acquisition '
  'path exists (intraday data is out of scope for the MVP).';
