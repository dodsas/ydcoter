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

-- InBody records (/inbody page) — values transcribed from the printed
-- InBody result sheet, one measurement per profile+date. Column names
-- follow the sheet's official English terms (SMM, PBF, WHR, ...).
-- 단백질 목표 g / 유지·감량 칼로리 are computed client-side, never stored;
-- lean_body_mass_kg is stored when printed on the sheet, otherwise the
-- client falls back to 체중 − 체지방량.
CREATE TABLE IF NOT EXISTS inbody_records (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id               INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    record_date              TEXT    NOT NULL,   -- ISO YYYY-MM-DD
    weight_kg                REAL    NOT NULL,   -- 체중
    skeletal_muscle_mass_kg  REAL    NOT NULL,   -- 골격근량 (SMM)
    body_fat_mass_kg         REAL    NOT NULL,   -- 체지방량
    percent_body_fat         REAL    NOT NULL,   -- 체지방률 PBF (결과지 인쇄값 그대로)
    bmi                      REAL,               -- BMI
    lean_body_mass_kg        REAL,               -- 제지방량 LBM (결과지 인쇄값)
    total_body_water_l       REAL,               -- 체수분
    protein_kg               REAL,               -- 단백질 (체성분)
    minerals_kg              REAL,               -- 무기질
    visceral_fat_level       INTEGER,            -- 내장지방레벨 (기준 10 이하)
    waist_hip_ratio          REAL,               -- 복부지방률 WHR (기준 0.90 이하, 남성)
    bmr_kcal                 INTEGER,            -- 기초대사량
    fat_control_kg           REAL,               -- 지방조절 권고 (음수 = 감량)
    muscle_control_kg        REAL,               -- 근육조절 권고 (양수 = 증량)
    inbody_score             INTEGER,            -- 인바디 점수
    note                     TEXT,
    created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (profile_id, record_date)
);

CREATE INDEX IF NOT EXISTS idx_inbody_profile_date ON inbody_records(profile_id, record_date);
