-- ydocter nutrition schema — applies to Turso in production
-- (`TURSO_DATABASE_URL`), or to the local DB in dev-fallback mode.
-- Holds the nutrient master list + per-profile daily food logs.
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

CREATE TABLE IF NOT EXISTS nutrients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    name_ko         TEXT    NOT NULL,
    name_en         TEXT,
    unit            TEXT    NOT NULL,
    category        TEXT    NOT NULL,      -- 'macro' | 'vitamin' | 'mineral' | 'other'
    rda             REAL,                   -- recommended daily allowance (adult male)
    ul              REAL,                   -- tolerable upper intake limit
    sort_order      INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    excess_warning  TEXT                    -- shown when intake exceeds target / UL
);

CREATE TABLE IF NOT EXISTS nutrition_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    log_date    TEXT    NOT NULL,
    meal_type   TEXT    NOT NULL,
    food_name   TEXT    NOT NULL,
    serving     TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS nutrition_values (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id      INTEGER NOT NULL REFERENCES nutrition_logs(id) ON DELETE CASCADE,
    nutrient_id INTEGER NOT NULL REFERENCES nutrients(id) ON DELETE CASCADE,
    amount      REAL    NOT NULL,
    UNIQUE (log_id, nutrient_id)
);

CREATE TABLE IF NOT EXISTS profile_nutrient_rda (
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    nutrient_id INTEGER NOT NULL REFERENCES nutrients(id) ON DELETE CASCADE,
    rda         REAL,
    ul          REAL,
    PRIMARY KEY (profile_id, nutrient_id)
);

CREATE INDEX IF NOT EXISTS idx_logs_profile_date ON nutrition_logs(profile_id, log_date);
CREATE INDEX IF NOT EXISTS idx_values_log        ON nutrition_values(log_id);
CREATE INDEX IF NOT EXISTS idx_values_nutrient   ON nutrition_values(nutrient_id);
