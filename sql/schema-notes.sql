-- ydocter health-notes schema — applies to Turso in production
-- (`TURSO_DATABASE_URL`), or to the local DB in dev-fallback mode.
-- 건강 관련 특이사항·개인 정보를 한 건당 하나의 원자적 사실(atomic fact)로
-- 축약 저장한다. /notes/context 가 카테고리별로 묶어 LLM 프롬프트에 바로
-- 주입 가능한 RAG 컨텍스트 텍스트로 변환한다.
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

CREATE TABLE IF NOT EXISTS health_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    category    TEXT    NOT NULL DEFAULT 'other',  -- condition | medication | allergy | symptom | lifestyle | family | goal | other
    title       TEXT    NOT NULL,                  -- 짧은 핵심 제목 ("요산 수치 경계")
    content     TEXT    NOT NULL,                  -- 축약된 사실 한 건 (RAG 청크 본문)
    tags        TEXT,                              -- 쉼표 구분 검색 키워드 ("요산,통풍,검진")
    pinned      INTEGER NOT NULL DEFAULT 0,        -- 1 = 중요 — 목록·컨텍스트 상단 고정
    archived    INTEGER NOT NULL DEFAULT 0,        -- 1 = 보관 — 컨텍스트 생성에서 제외
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notes_profile ON health_notes(profile_id, archived, category);
