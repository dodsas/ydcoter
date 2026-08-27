# 데이터 저장소 구성

ydocter 는 두 개의 DB 백엔드를 동시에 사용한다. 어떤 데이터가 어디에 사는지,
왜 그렇게 나뉘었는지, 어떻게 흐르는지를 한 곳에 정리한다.

## 백엔드 두 개

| 백엔드 | 위치 | 역할 | 영속성 |
|---|---|---|---|
| **Local SQLite** | `data/health.db` (git-tracked) | 건강검진 기록 (변동이 거의 없는 정적 데이터) | 파일 — 배포에 함께 ship |
| **Turso (libSQL)** | `TURSO_DATABASE_URL` (원격) | 영양 로그 (매일 사용자가 추가) | 원격 DB — 배포와 무관하게 누적 |

분리한 이유:
- 건강검진 데이터는 1년에 한 번 갱신되고, 코드 리뷰 + git diff 로 추적되는 게 자연스럽다.
- 영양 로그는 사용자가 매일 입력하므로 git 에 두면 충돌·소실 위험이 있다. 원격 DB 가 적합.
- Turso 의 Hrana HTTP 프로토콜은 idle stream 을 끊으므로, 자주 안 쓰는 데이터(검진)에는
  굳이 네트워크 round-trip 을 부담시키지 않는다.

## 스키마 매핑

### Local SQLite (`data/health.db`)

스키마: [`sql/schema-health.sql`](../sql/schema-health.sql)

| 객체 | 종류 | 행 수 (현재) | 설명 |
|---|---|---|---|
| `profiles` | table | 2 | 프로필 (떠니/쭈니). 슬러그, 표시명, 성별, 출생년도, 신장. |
| `test_items` | table | 198 | 검진 항목 카탈로그. 프로필×항목 별 ref_min/ref_max/ref_indicator 등. |
| `measurements` | table | 335 | 연도별 측정값 (`item_id` × `year` 유니크). 수치 + 원문 텍스트. |
| `v_measurements` | view | — | `measurements` ⨝ `test_items` ⨝ `profiles` 에 LOW/NORMAL/HIGH 상태를 동적으로 계산해 붙임. |

### Turso (production)

스키마: [`sql/schema-nutrition.sql`](../sql/schema-nutrition.sql)

| 객체 | 종류 | 행 수 (현재) | 설명 |
|---|---|---|---|
| `profiles` | table | 2 | **로컬과 동일한 id 로 미러링**되는 FK 타겟. 권위 있는 읽기 경로는 로컬. |
| `nutrients` | table | 36 | 영양소 카탈로그 (kcal, protein, vitamin_*, mineral_* 등). RDA/UL 기본값 보유. |
| `nutrition_logs` | table | 40 | 사용자 식사 기록. `profile_id × log_date × meal_type × food_name`. |
| `nutrition_values` | table | 646 | 각 로그가 함유한 영양소 양. `log_id × nutrient_id` 유니크. |
| `profile_nutrient_rda` | table | 72 | 프로필별 RDA/UL 오버라이드 (성별·체격에서 derive). NULL = 카탈로그 기본값. |
| `body_records` | table | — | 둘레 측정 기록 (`sql/schema-body.sql`). `profile_id × record_date` 유니크. |
| `workout_sessions` / `workout_sets` | table | — | 운동 세션 + 세트 (`sql/schema-body.sql`). |
| `inbody_records` | table | — | 인바디 결과지 옮겨적기 (`sql/schema-body.sql`). 체중·골격근량·체지방량·체지방률(필수) + 내장지방Lv·WHR·BMR·지방/근육조절·메모. LBM·단백질 목표·칼로리는 클라이언트 파생, 미저장. |

> **`profiles` 가 양쪽에 있는 이유**: Turso 의 `nutrition_logs` / `profile_nutrient_rda` 가
> FK 로 `profiles(id)` 를 참조하므로 Turso 에도 같은 row 가 필요하다. 로컬에서 INSERT
> 후 같은 `id` 로 Turso 에 미러링하여 두 DB 가 동일 식별자를 공유한다.

## Dev-fallback 모드

`TURSO_DATABASE_URL` 이 없으면 nutrition 도 로컬 SQLite 로 떨어진다.
이때 로컬 한 파일에 두 스키마가 모두 적용된다 (`init_nutrition_schema` 가 `_ensure_schema`
시작 시 적용). 현재 로컬 파일에 `nutrients (36)`, `nutrition_logs (12)`, `nutrition_values (220)`,
`profile_nutrient_rda (72)` 가 남아있는 건 dev-fallback 호환을 위한 잔존이며 production 경로에서는 사용되지 않는다.

## 읽기/쓰기 경로 (app/main.py)

| 엔드포인트 | Local 사용 | Turso 사용 |
|---|---|---|
| `GET /health` | profiles, test_items, measurements (카운트) | — (백엔드 식별만) |
| `GET /profiles` | profiles + test_items + measurements (집계) | — |
| `GET /categories` | test_items | — |
| `GET /items*`, `GET /items/{id}/trend` | test_items, v_measurements | — |
| `GET /measurements`, `GET /abnormal/{year}` | v_measurements | — |
| `PATCH /items/{id}/reference` | test_items (write) | — |
| `GET /nutrition/dates` | profiles (slug→id 해석) | nutrition_logs ⨝ values ⨝ nutrients |
| `GET /nutrition/{date}` | profiles (slug→id) | nutrition_logs, nutrition_values, nutrients, profile_nutrient_rda |
| `POST /nutrition/{date}/parse` | profiles (slug→id) | nutrients (read), nutrition_logs / nutrition_values (write, 사이에 Claude 호출이 있어 read/write 사이에 conn 재오픈) |
| `GET /nutrients` | — | nutrients |
| `GET/PUT/DELETE /body/records*` | profiles (slug→id) | body_records |
| `GET/PUT/DELETE /workout/sessions*` | profiles (slug→id) | workout_sessions, workout_sets |
| `GET/PUT/DELETE /inbody/records*` | profiles (slug→id) | inbody_records |

> **연결 분리 규칙**: 한 endpoint 안에서 두 DB 를 모두 써야 하면 각각 별도 `with`
> 블록으로 처리한다. Turso 는 idle stream 을 끊으므로 같은 연결을 외부 호출(Claude 등) 전후로 유지하면 안 된다 (`app/main.py:472-475` 참고).

## 시드 데이터 출처

| 모듈 | export | 대상 |
|---|---|---|
| `app/seed_data.py` | `PROFILES`, `RECORDS` | `profiles`, `test_items`, `measurements` |
| `app/nutrition_data.py` | `NUTRIENTS`, `LOGS`, `RDA_BY_SEX`, `estimate_kcal_tdee()` | `nutrients`, `nutrition_logs`, `nutrition_values`, `profile_nutrient_rda` |

시딩은 `python -m app.load_data` 가 수행한다. 빈 DB 한정으로만 자동 시드되며 (`profiles`
행이 있으면 skip), `--reset` 으로 강제 재시드한다.

## DDL / migration 파일

| 파일 | 목적 |
|---|---|
| `sql/schema-health.sql` | Local 에 적용. profiles + test_items + measurements + `v_measurements` view. |
| `sql/schema-nutrition.sql` | Turso (or dev-fallback local) 에 적용. nutrients + nutrition_* + `profiles` FK 타겟. |
| `sql/schema-body.sql` | Turso (or dev-fallback local) 에 적용. body_records + workout_sessions/sets + inbody_records + `profiles` FK 타겟. |
| `sql/turso-cleanup.sql` | 일회성. 분리 이전에 Turso 에 만들어졌던 잔재 (`test_items`, `measurements`, `v_measurements`, `v_daily_nutrition`) 를 idempotent 하게 DROP. |

## CLI

```bash
# 안전 (기본): 스키마 적용, 비어있을 때만 시드
python -m app.load_data

# 강제 리셋 — 로컬만 권장
python -m app.load_data --reset

# 스키마만 (시드 skip)
python -m app.load_data --keep

# Turso 에서 레거시 테이블/뷰 제거 (idempotent, TURSO_DATABASE_URL 필수)
python -m app.load_data --turso-cleanup
```

## 환경 변수

| 변수 | 용도 |
|---|---|
| `TURSO_DATABASE_URL` | Turso 엔드포인트. 설정 시 nutrition 이 원격으로 분기. 없으면 dev-fallback. |
| `TURSO_AUTH_TOKEN` | Turso 인증 토큰. |
| `YDOCTER_DB_PATH` | 로컬 SQLite 경로 override. 기본 `data/health.db`. |
| `YCLAUDE_BASE_URL`, `YCLAUDE_API_KEY` | `/nutrition/{date}/parse` 의 LLM 호출용. 미설정 시 503. |
| `RENDER_GIT_COMMIT` | 배포 환경에서 `/version` 이 보여주는 커밋 해시. |
