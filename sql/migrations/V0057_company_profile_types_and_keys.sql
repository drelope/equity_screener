-- V0057: Type and key corrections for the clean company profile.
--
-- * earnings_timestamp is an instant (earnings call start), not a calendar
--   date; truncating it to a UTC date shifted after-close US calls to the
--   next day. It becomes TIMESTAMPTZ like earnings_timestamp_end.
-- * cik / issuer_id are denormalized from reference.securities so profiles can
--   be joined to issuer-level data without a second hop.
-- * company_officer gains the surrogate profile_id parent key. The
--   (symbol, parent_name) natural key is kept for compatibility, but
--   profile_id is the stable join key.

DO $migration$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'clean'
      AND table_name = 'company_profile'
      AND column_name = 'earnings_timestamp'
      AND data_type = 'date'
  ) THEN
    ALTER TABLE clean.company_profile
      ALTER COLUMN earnings_timestamp TYPE TIMESTAMPTZ
      USING (earnings_timestamp::timestamp AT TIME ZONE 'UTC');
  END IF;
END
$migration$;

COMMENT ON COLUMN clean.company_profile.earnings_timestamp IS
  'Earnings event start converted from Unix epoch seconds to a UTC timestamp';

ALTER TABLE clean.company_profile
  ADD COLUMN IF NOT EXISTS cik VARCHAR(10),
  ADD COLUMN IF NOT EXISTS issuer_id BIGINT;

UPDATE clean.company_profile cp
SET cik = s.cik,
    issuer_id = s.issuer_id
FROM reference.securities s
WHERE s.security_id = cp.reference_security_id
  AND (cp.cik IS DISTINCT FROM s.cik OR cp.issuer_id IS DISTINCT FROM s.issuer_id);

CREATE INDEX IF NOT EXISTS ix_clean_company_profile_cik
  ON clean.company_profile (cik);

COMMENT ON COLUMN clean.company_profile.cik IS
  'SEC CIK of the matched reference security (reference.securities.cik)';
COMMENT ON COLUMN clean.company_profile.issuer_id IS
  'Issuer key of the matched reference security (reference.securities.issuer_id)';

ALTER TABLE clean.company_officer
  ADD COLUMN IF NOT EXISTS profile_id BIGINT;

UPDATE clean.company_officer o
SET profile_id = cp.profile_id
FROM clean.company_profile cp
WHERE cp.symbol = o.symbol
  AND cp.parent_name = o.parent_name
  AND o.profile_id IS DISTINCT FROM cp.profile_id;

ALTER TABLE clean.company_officer
  ALTER COLUMN profile_id SET NOT NULL;

DO $migration$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_clean_company_officer_profile_id'
      AND conrelid = 'clean.company_officer'::regclass
  ) THEN
    ALTER TABLE clean.company_officer
      ADD CONSTRAINT fk_clean_company_officer_profile_id
      FOREIGN KEY (profile_id)
      REFERENCES clean.company_profile(profile_id)
      ON DELETE CASCADE;
  END IF;
END
$migration$;

CREATE INDEX IF NOT EXISTS ix_clean_company_officer_profile_id
  ON clean.company_officer (profile_id);

COMMENT ON COLUMN clean.company_officer.profile_id IS
  'Surrogate parent key to clean.company_profile.profile_id; preferred join key over (symbol, parent_name)';
