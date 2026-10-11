-- V0058: clean.ticker_profile.source_profiles carries lineage, not payloads.
--
-- Each element used to embed the full raw_payload (OpenBB profile, officers,
-- SEC evidence), duplicating raw.ticker_profile into every curated row. It now
-- holds security_id, provider, retrieved_at, payload_hash (md5 of the raw
-- payload text), field_sources (loader that set each typed column) and the
-- classification evidence. The payload is retrieved from raw.ticker_profile or
-- raw.ticker_profile_load when needed. The rebuild script rewrites the data.

COMMENT ON COLUMN clean.ticker_profile.source_profiles IS
  'Lineage of every contributing raw.ticker_profile row: security_id, provider, retrieved_at, payload_hash (md5 of raw_payload text), field_sources and classification evidence; payloads stay in the raw schema';
