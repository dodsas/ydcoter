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

-- Workout sessions (/workout page) — one session per profile+date,
-- sets stored relationally so per-exercise progression is queryable.
CREATE TABLE IF NOT EXISTS workout_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    session_date  TEXT    NOT NULL,               -- ISO YYYY-MM-DD
    phase         INTEGER NOT NULL DEFAULT 1,     -- 1: 머신 5종 적응기, 2: 7종 전신
    discomfort    INTEGER,                        -- 세션 후 허리 불편감 0~10
    note          TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (profile_id, session_date)
);

CREATE TABLE IF NOT EXISTS workout_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    exercise    TEXT    NOT NULL,                 -- slug: legpress, chestpress, ...
    set_no      INTEGER NOT NULL,                 -- 1..n
    weight_kg   REAL,
    reps        INTEGER,
    UNIQUE (session_id, exercise, set_no)
);

CREATE INDEX IF NOT EXISTS idx_wsession_profile_date ON workout_sessions(profile_id, session_date);
CREATE INDEX IF NOT EXISTS idx_wsets_session          ON workout_sets(session_id);
