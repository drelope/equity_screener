-- Prevent repeated officer records from being loaded for the same company.
-- NULL titles compare as equal so an undisclosed title does not bypass the
-- idempotency key. Existing data was audited for collisions before applying.
DO $migration$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM clean.company_officer
    GROUP BY symbol, parent_name, name, title
    HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION
      'Cannot add officer identity constraint: duplicate (symbol, parent_name, name, title) rows exist';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'clean.company_officer'::regclass
      AND conname = 'uq_clean_company_officer_identity'
  ) THEN
    ALTER TABLE clean.company_officer
      ADD CONSTRAINT uq_clean_company_officer_identity
      UNIQUE NULLS NOT DISTINCT (symbol, parent_name, name, title);
  END IF;
END
$migration$;

COMMENT ON CONSTRAINT uq_clean_company_officer_identity
ON clean.company_officer IS
  'Idempotency key for one named officer and title per company; NULL title participates in uniqueness';