-- ydocter health records schema (SQLite)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

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

-- ===========================================================================
-- Nutrition tracking
-- ===========================================================================

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
    log_date    TEXT    NOT NULL,           -- ISO date 'YYYY-MM-DD'
    meal_type   TEXT    NOT NULL,           -- 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'supplement'
    food_name   TEXT    NOT NULL,
    serving     TEXT,                       -- free-text serving description
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

-- Per-profile RDA / UL overrides. NULL = inherit nutrients.rda / nutrients.ul.
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

DROP VIEW IF EXISTS v_daily_nutrition;
CREATE VIEW v_daily_nutrition AS
SELECT
    l.profile_id,
    p.slug                         AS profile_slug,
    l.log_date,
    n.id                           AS nutrient_id,
    n.code                         AS nutrient_code,
    n.name_ko,
    n.name_en,
    n.unit,
    n.category,
    COALESCE(po.rda, n.rda)        AS rda,
    COALESCE(po.ul,  n.ul)         AS ul,
    n.excess_warning,
    n.sort_order,
    SUM(v.amount)                  AS total
FROM nutrition_logs   l
JOIN nutrition_values v ON v.log_id = l.id
JOIN nutrients        n ON n.id = v.nutrient_id
JOIN profiles         p ON p.id = l.profile_id
LEFT JOIN profile_nutrient_rda po
    ON po.profile_id = l.profile_id AND po.nutrient_id = n.id
GROUP BY l.profile_id, l.log_date, n.id;

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
