-- ydocter body-measurement schema — applies to Turso in production
-- (`TURSO_DATABASE_URL`), or to the local DB in dev-fallback mode.
-- Holds monthly circumference records per profile; body fat % / lean
-- mass / FFMI are derived client-side (Navy method), never stored.
--
-- `profiles` is duplicated here as a FK target. Identical definition to
-- schema-health.sql; both files are idempotent (CREATE IF NOT EXISTS).
-- The authoritative read path for profiles is the local DB.

CREATE TABLE IF NOT EXISTS profiles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    note          TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    sex           TEXT,
    birth_year    INTEGER,
    height_cm     REAL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS body_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    record_date  TEXT    NOT NULL,               -- ISO YYYY-MM-DD
    sex          TEXT    NOT NULL DEFAULT 'm',   -- 'm' | 'f' (Navy formula variant)
    height_cm    REAL    NOT NULL,
    weight_kg    REAL    NOT NULL,
    neck_cm      REAL    NOT NULL,
    waist_cm     REAL    NOT NULL,
    hip_cm       REAL,                           -- required by the female formula
    chest_cm     REAL,
    arm_cm       REAL,
    shoulder_cm  REAL,
    thigh_cm     REAL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (profile_id, record_date)
);

CREATE INDEX IF NOT EXISTS idx_body_profile_date ON body_records(profile_id, record_date);
