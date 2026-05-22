-- ydocter health-records schema — applies to the local SQLite DB
-- (`data/health.db`) that ships in git. Holds profiles + test catalog +
-- yearly lab measurements. Not used on Turso.
--
-- `profiles` is duplicated in schema-nutrition.sql (idempotent CREATE IF
-- NOT EXISTS) because Turso's nutrition_* tables FK-reference it.

CREATE TABLE IF NOT EXISTS profiles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    note          TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    sex           TEXT,                 -- 'male' | 'female' | NULL
    birth_year    INTEGER,
    height_cm     REAL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id        INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    major_category    TEXT    NOT NULL,
    minor_category    TEXT    NOT NULL,
    code              TEXT,
    name              TEXT    NOT NULL,
    unit              TEXT,
    ref_min           REAL,
    ref_max           REAL,
    ref_indicator     TEXT,
    related_diseases  TEXT,
    memo              TEXT,
    UNIQUE (profile_id, major_category, minor_category, name)
);

CREATE TABLE IF NOT EXISTS measurements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER NOT NULL REFERENCES test_items(id) ON DELETE CASCADE,
    year          INTEGER NOT NULL,
    value_numeric REAL,
    value_text    TEXT,
    UNIQUE (item_id, year)
);

CREATE INDEX IF NOT EXISTS idx_items_profile ON test_items(profile_id);
CREATE INDEX IF NOT EXISTS idx_items_major   ON test_items(major_category);
CREATE INDEX IF NOT EXISTS idx_items_minor   ON test_items(minor_category);
CREATE INDEX IF NOT EXISTS idx_measure_item  ON measurements(item_id);
CREATE INDEX IF NOT EXISTS idx_measure_year  ON measurements(year);

DROP VIEW IF EXISTS v_measurements;
CREATE VIEW v_measurements AS
SELECT
    m.id           AS measurement_id,
    i.id           AS item_id,
    i.profile_id,
    p.slug         AS profile_slug,
    p.display_name AS profile_name,
    i.major_category,
    i.minor_category,
    i.code,
    i.name,
    i.ref_min,
    i.ref_max,
    i.related_diseases,
    m.year,
    m.value_numeric,
    m.value_text,
    CASE
        WHEN m.value_numeric IS NULL THEN NULL
        WHEN i.ref_min IS NOT NULL AND m.value_numeric < i.ref_min THEN 'LOW'
        WHEN i.ref_max IS NOT NULL AND m.value_numeric > i.ref_max THEN 'HIGH'
        ELSE 'NORMAL'
    END AS status
FROM measurements m
JOIN test_items   i ON i.id = m.item_id
JOIN profiles     p ON p.id = i.profile_id;
