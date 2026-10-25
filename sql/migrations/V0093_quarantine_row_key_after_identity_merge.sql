-- V0093 quarantine_row_key_after_identity_merge
--
-- V0092 merged 16 duplicate identities into their winners and deleted or
-- re-pointed their fundamentals rows. audit.quarantined_values keys each parked
-- value as security_id|period_end|fiscal_period|filed, so unresolved entries
-- still carried the removed loser id and no longer matched a row. The parked
-- value itself is unchanged: where a loser copy was deleted, the winner's copy
-- is identical in every column except retrieved_at (checked before V0092).
--
-- Two cases:
--   1. The winner has no entry for the same value: the key is rewritten to the
--      winner id, keeping the rest of the key.
--   2. The winner already has an unresolved entry for the same table, column and
--      value: the rewrite would violate the unique key. The loser entry is closed
--      with a note and kept, not deleted.

CREATE TEMP TABLE merged_identity (old_id text PRIMARY KEY, new_id text NOT NULL) ON COMMIT DROP;
INSERT INTO merged_identity (old_id, new_id) VALUES
    ('1140279d-4e29-56e7-acaf-88364ccedf26', 'e75820ae-e595-59f3-acd4-01592e001c24'),
    ('12b0bd57-3a87-5bc7-8466-b939920f6260', 'c0653eb1-baca-5568-8cd0-a3802dc02999'),
    ('253c569b-50d8-502d-99d2-df3806dda000', 'dcf7db52-d414-558b-a82d-28814241efd9'),
    ('40dd0731-d679-594e-a435-7324f332578a', '255e0195-5076-5d96-83b3-40c7605885bd'),
    ('4821f9a0-7dce-5252-8023-68c15db02dea', 'e808ac91-7fa9-5dbe-9388-a382e6fe9ed4'),
    ('54739c0d-3037-5a32-bd6d-63e20140e213', 'fc4ffa41-e859-5bea-82f9-dacaba815074'),
    ('6882f234-ecd8-5334-83dc-b4bae8a2fc47', '31153a9e-2ff1-598c-9828-480e203c26e1'),
    ('691ba69a-f94e-5e14-b33b-b29d785eee40', 'db1771da-7080-5688-8e41-352a55cbbe48'),
    ('6d462d90-6817-5f8b-b324-d76078c0fb51', 'bb781979-2ddd-5192-b3d7-8f4ec73c6258'),
    ('70065916-a72f-5eef-91a6-8549f286956b', '9d27822f-b7b2-5fb7-aa87-75a06603a071'),
    ('8fde194b-1605-521d-9071-f01e0bf12006', '58578821-b8a3-5a0d-be34-d3962ee67518'),
    ('a327a119-e70d-5fa7-9481-44f6b033b30f', '81f575d8-b1c8-594f-9fa4-bbfb0ca53e2a'),
    ('bebe1002-f506-59f7-96e2-7d6f3637afa2', 'a8f6740f-b44a-5f2a-af4c-20bb945ee806'),
    ('da8421b2-553f-5155-8a75-b9510c6de2d0', '35934b2b-1ca6-597e-aa98-29d48db0e9b5'),
    ('f1b4bb95-db97-5ebf-8806-e4bd5b9dfd6d', 'a06dc9b0-1372-5e43-99e3-ad0233a41bcc'),
    ('f60558d4-16dd-54bd-a366-0416dc5af1ea', '54ed1c53-ac95-5d20-96db-ab0513cac304');

UPDATE audit.quarantined_values q
SET resolved_at = now(),
    resolution_note = 'duplicate of the winner entry after the V0092 identity merge; '
                      'the same value is still parked under the winner id'
FROM merged_identity m
WHERE q.resolved_at IS NULL
  AND q.table_schema = 'fundamentals'
  AND split_part(q.row_key, '|', 1) = m.old_id
  AND EXISTS (
      SELECT 1 FROM audit.quarantined_values w
      WHERE w.table_schema = q.table_schema
        AND w.table_name = q.table_name
        AND w.column_name = q.column_name
        AND w.observed_value = q.observed_value
        AND w.row_key = m.new_id || substring(q.row_key from 37)
  );

UPDATE audit.quarantined_values q
SET row_key = m.new_id || substring(q.row_key from 37)
FROM merged_identity m
WHERE q.resolved_at IS NULL
  AND q.table_schema = 'fundamentals'
  AND split_part(q.row_key, '|', 1) = m.old_id;

-- Every unresolved fundamentals entry must now match a row again.
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n
    FROM audit.quarantined_values q
    WHERE q.resolved_at IS NULL
      AND q.table_schema = 'fundamentals'
      AND NOT EXISTS (
          SELECT 1 FROM fundamentals.periodic_financials f
          WHERE concat_ws('|', f.security_id, f.period_end, f.fiscal_period, f.filed) = q.row_key
      );
    IF n > 0 THEN
        RAISE EXCEPTION 'V0093: % unresolved fundamentals quarantine entries still unmatched', n;
    END IF;
END $$;
