-- V0098: A point-in-time identifier table for securities.
--
-- reference.securities holds one ticker, cik, cusip and isin per row, so a ticker
-- that moved to another security, or a symbol change, could only be expressed by
-- overwriting history. This table keeps every identifier a security has carried,
-- with the interval it was valid, so "who was ticker X on date D" has an answer.
--
-- valid_from NULL means the start is unknown (the identifier predates the data);
-- valid_to NULL means it is current.
BEGIN;

CREATE TABLE IF NOT EXISTS reference.security_identifiers (
  identifier_id BIGSERIAL PRIMARY KEY,
  security_id UUID NOT NULL REFERENCES reference.securities(security_id),
  id_type VARCHAR(8) NOT NULL CHECK (id_type IN ('cik', 'cusip', 'isin', 'ticker')),
  id_value VARCHAR(32) NOT NULL,
  valid_from DATE,
  valid_to DATE,
  source VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
  CONSTRAINT security_identifiers_unique UNIQUE (security_id, id_type, id_value)
);

CREATE INDEX IF NOT EXISTS security_identifiers_lookup_idx
  ON reference.security_identifiers (id_type, id_value);

COMMENT ON TABLE reference.security_identifiers IS
  'Every cik/cusip/isin/ticker a security has carried, with its validity interval';

INSERT INTO reference.security_identifiers (security_id, id_type, id_value, valid_to, source)
SELECT security_id, 'cik', cik, delisted_date, 'reference.securities'
FROM reference.securities WHERE cik IS NOT NULL AND btrim(cik) <> ''
ON CONFLICT DO NOTHING;

INSERT INTO reference.security_identifiers (security_id, id_type, id_value, valid_to, source)
SELECT security_id, 'ticker', upper(ticker), delisted_date, 'reference.securities'
FROM reference.securities WHERE ticker IS NOT NULL AND btrim(ticker) <> ''
ON CONFLICT DO NOTHING;

INSERT INTO reference.security_identifiers (security_id, id_type, id_value, valid_to, source)
SELECT security_id, 'cusip', upper(cusip), delisted_date, 'reference.securities'
FROM reference.securities WHERE cusip IS NOT NULL AND btrim(cusip) <> ''
ON CONFLICT DO NOTHING;

INSERT INTO reference.security_identifiers (security_id, id_type, id_value, valid_to, source)
SELECT security_id, 'isin', upper(isin), delisted_date, 'reference.securities'
FROM reference.securities WHERE isin IS NOT NULL AND btrim(isin) <> ''
ON CONFLICT DO NOTHING;

COMMIT;
