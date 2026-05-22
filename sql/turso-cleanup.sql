-- One-time Turso cleanup: drop tables/views that were created by the
-- pre-split unified schema but are no longer referenced after the
-- health/nutrition DB split.
--
-- Health records (test_items, measurements, v_measurements) now live
-- exclusively on the local SQLite file. The rows that existed on Turso
-- are identical to the local copies (verified before this script was
-- written), so dropping them here loses no user data.
--
-- v_daily_nutrition was an aggregation view that the application stopped
-- querying; the equivalent JOIN is now computed inline in
-- _load_daily_nutrition() so un-logged nutrients still surface.
--
-- Idempotent — running it twice is a no-op.
--
-- Apply via:  python -m app.load_data --turso-cleanup

DROP VIEW  IF EXISTS v_measurements;
DROP VIEW  IF EXISTS v_daily_nutrition;
DROP TABLE IF EXISTS measurements;
DROP TABLE IF EXISTS test_items;
