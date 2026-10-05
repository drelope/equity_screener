-- V0039 deactivate_superseded_security_duplicates
--
-- 61 pairs of active reference.securities rows share (cik, ticker) and both
-- carry dividend = TRUE. They are not arbitrary collisions: each pair is one
-- economic security described two ways, where security_type was inferred from
-- security_name and a re-classification minted a second row when the name or
-- type changed. ALTI, for example, exists twice:
--
--   common_stock   "Class A ordinary shares, par value ..."   (created 09-23)
--   preferred_stock "AlTi Global, Inc."                        (created 09-13)
--
-- The same ticker therefore got ingested, feature-built and scored twice.
--
-- Survivor rule: within each duplicate (cik, ticker) group keep the most
-- recently created row and deactivate the older one. This is not a heuristic
-- on the name -- it is observed to be the re-classification batch: every older
-- row dates from the original classification pass and every survivor from the
-- 2026-09-23 13:08 pass. Deactivation mirrors what V0034 already did for
-- securities whose security_id changed under them, so the historical rows
-- (features, scores, rankings, predictions) stay in place and only the
-- current-state flag moves.
--
-- Zero impact on the published universe, and that was checked rather than
-- assumed:
--   * none of the 61 rows being deactivated holds a composite_score at the
--     run date -- their surviving twin does in every case, so no security
--     leaves model.scores;
--   * 58 of the 61 survivors carry model.features (the other 3 are pairs with
--     no features on either side, e.g. ATEKW).
--
-- The dividend flag is deliberately left untouched. Narrowing it is a separate
-- change with a much larger blast radius, recorded in V0040.

UPDATE reference.securities s
SET active = FALSE
WHERE s.active
  AND s.dividend
  AND EXISTS (
      SELECT 1
      FROM reference.securities t
      WHERE t.cik = s.cik
        AND t.ticker = s.ticker
        AND t.security_id <> s.security_id
        AND t.active
        AND t.dividend
        AND t.created_at > s.created_at
  );
