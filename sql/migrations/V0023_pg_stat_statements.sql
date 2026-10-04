-- docker-compose.yml preloads pg_stat_statements through
-- shared_preload_libraries, but preloading only makes the library available to
-- CREATE EXTENSION. Nothing created it, so the pg_stat_statements view the
-- setting exists to expose was never present and the preload was pure overhead
-- on every connection.
--
-- schema.sql carries the same statement for fresh bootstraps (the compose
-- initdb.d mount runs schema.sql only, not the migrations); this file is what
-- brings an already-initialised database in line.
--
-- Requires the preload. On a server started without
-- `shared_preload_libraries=pg_stat_statements` this raises instead of silently
-- doing nothing, which is the signal you want -- the view would not work anyway.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
