# ydocter API 레퍼런스

클라이언트 개발용 문서. 각 엔드포인트마다 **무슨 값을 어떤 제약으로 보낼 수 있는지**와
요청/응답 예시를 제공한다. 라이브로 쏴보는 용도는 Swagger(`/docs`)를 쓰고,
구현할 때는 이 문서를 기준으로 삼으면 된다.

서버에서 보는 법: 렌더링된 뷰어 **`/apidoc`** · 원문 **`/docs/API.md`**

- 로컬: `http://127.0.0.1:8000`
- 모든 요청/응답은 JSON (`Content-Type: application/json`)
- 날짜는 전부 ISO `YYYY-MM-DD` 문자열. 형식이 틀리면 `422`.

---

## 공통 규칙

### 1. `profile` 쿼리 파라미터

개인 데이터를 다루는 모든 엔드포인트는 `?profile=` 로 대상 프로필을 지정한다.

| 값 | 동작 |
|---|---|
| 슬러그 (`tteoni`) | 해당 프로필 |
| 한글 표시 이름 (`떠니`) | 동일하게 매칭됨 (수기 URL 편의) |
| 생략 | **첫 번째 프로필**로 폴백 (`sort_order, id` 순) |
| 존재하지 않는 값 | `404 {"detail": "profile 'x' not found"}` |

유효한 슬러그 목록은 `GET /profiles` 로 조회.

### 2. 에러 응답 포맷

| 상황 | 상태 | 바디 |
|---|---|---|
| 리소스 없음 / 도메인 검증 실패 | 404 / 422 등 | `{"detail": "사람이 읽는 메시지"}` |
| Pydantic 필드 검증 실패 | 422 | `{"detail": [{"type": "...", "loc": [...], "msg": "...", ...}]}` (배열) |

클라이언트는 `detail`이 문자열일 수도, 배열일 수도 있다는 걸 처리해야 한다.

### 3. 요청 바디는 엄격 모드

모든 쓰기 payload 는 `extra: forbid` — **스키마에 없는 필드를 보내면 422**.
필드명 오타가 조용히 무시되지 않으니 아래 필드 표를 정확히 따를 것.

### 4. Upsert 패턴

`PUT /{리소스}/records/{record_date}` 형태는 전부 **날짜가 자연키인 upsert**다.
같은 날짜로 다시 PUT 하면 기존 레코드가 통째로 교체된다. 부분 수정(PATCH) 개념이
없으므로 수정 시에도 전체 필드를 보내야 한다.

---

## 시스템

### `GET /health` — 서버 상태

파라미터 없음.

```json
{
  "status": "ok",
  "profiles": 2, "items": 198, "measurements": 335,
  "health_backend": "sqlite",
  "health_db": "/app/data/health.db",
  "nutrition_backend": "turso",
  "nutrition_db": "libsql://..."
}
```

### `GET /version` — 배포 버전 (Swagger 미노출)

```json
{ "commit": "b2db621...", "commit_short": "b2db621", "deployed_at": "2026-10-30T06:00:00+00:00", "data_version": "b2db621.0" }
```

`data_version` 은 참고치 수정 시마다 바뀜 — 클라이언트 캐시 무효화 키로 사용.

---

## 프로필

### `GET /profiles` — 프로필 목록

파라미터 없음. 응답 (배열):

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | int | 내부 id (클라이언트는 보통 `slug`만 쓰면 됨) |
| `slug` | string | `?profile=` 에 넣는 값 |
| `display_name` | string | 한글 표시 이름 |
| `note` | string \| null | |
| `sort_order` | int | |
| `sex` | string \| null | `m`/`f` 또는 `male`/`female` 혼재 |
| `birth_year` | int \| null | |
| `height_cm` | float \| null | |
| `item_count`, `measurement_count` | int | 검진 데이터 보유량 |

---

## 건강검진 기록 (읽기 전용 + 참고치 수정)

연 1회 건강검진 결과. 데이터 적재는 서버 측 스크립트로만 하고, API 로는 조회와
참고치(정상 범위) 수정만 가능.

### `GET /categories` — 대분류/소분류 목록

| 쿼리 | 타입 | 설명 |
|---|---|---|
| `profile` | string | 공통 규칙 참조 |

응답: `[{"major_category": "혈액검사", "minor_category": "간기능", "item_count": 8}, ...]`

### `GET /items` — 검사 항목 목록

| 쿼리 | 타입 | 설명 |
|---|---|---|
| `profile` | string | |
| `major` | string | 대분류 필터 |
| `minor` | string | 소분류 필터 |
| `q` | string | 이름/코드 부분 검색 |

응답 항목 필드: `id, profile_id, major_category, minor_category, code, name, unit, ref_min, ref_max, ref_indicator, related_diseases, memo` (code/unit/ref_* /related_diseases/memo 는 null 가능).

### `GET /items/{item_id}` — 항목 단건. 없으면 404.

### `GET /items/{item_id}/trend` — 항목의 연도별 추이

```json
{
  "item": { "...": "GET /items 와 동일한 항목 객체" },
  "points": [ { "year": 2023, "value_numeric": 7.2, "value_text": null, "status": "HIGH" }, ... ]
}
```

`status`: `"NORMAL" | "LOW" | "HIGH" | null` (참고치 없는 항목은 null).

### `GET /measurements` — 측정값 목록

| 쿼리 | 타입 | 설명 |
|---|---|---|
| `profile` | string | |
| `year` | int | 검진 연도 |
| `status` | string | `NORMAL` / `LOW` / `HIGH` (대소문자 무관) |
| `major`, `minor` | string | 분류 필터 |

응답 항목: `measurement_id, item_id, profile_id, profile_slug, year, value_numeric, value_text, status`.

### `GET /abnormal/{year}` — 해당 연도의 이상치(LOW/HIGH)만

경로의 `year` 는 int. 응답은 `/measurements` 와 동일 형태.

### `GET /dashboard/health-records` — 최근 N개 검진 연도 통합 조회

| 쿼리 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `years` | int | 1~30, 기본 1 | 달력 기준이 아니라 **기록이 있는 연도** 기준 최신 N개 |
| `profile` | string | | |

```json
{
  "years": [2025, 2023],
  "records": [
    { "year": 2025, "major_category": "혈액검사", "minor_category": "신장기능", "code": "UA",
      "name": "요산", "unit": "mg/dL", "value_numeric": 7.2, "value_text": null,
      "ref_min": 3.0, "ref_max": 7.0, "status": "HIGH" }
  ]
}
```

항목 메타(이름/단위/참고치)가 포함된 자기완결 행이라 `/items` 조인이 불필요.

### `PATCH /items/{item_id}/reference` — 참고치 수정

**유일하게 생략/null 의미가 다른 엔드포인트.**

| 필드 | 타입 | 의미 |
|---|---|---|
| `ref_min` | float \| null | **생략** = 기존값 유지, **null 명시** = 하한 제거 |
| `ref_max` | float \| null | 위와 동일 |
| `ref_indicator` | string \| null | 위와 동일. 빈 문자열은 null 처리 |

제약: 최종적으로 `ref_min ≤ ref_max` 여야 함 (위반 시 422).

```bash
curl -X PATCH http://127.0.0.1:8000/items/42/reference \
  -H 'Content-Type: application/json' \
  -d '{"ref_max": 7.0}'          # ref_min은 건드리지 않음
```

응답: 수정된 항목 객체 (`GET /items/{id}` 와 동일). status 는 다음 조회부터 재계산됨.

---

## 영양 (식단 기록)

### `GET /nutrition/dates` — 기록이 있는 날짜 목록 (최신순)

| 쿼리 | `profile` |
|---|---|

응답: `[{"log_date": "2026-10-29", "entry_count": 4, "kcal": 1850.0}, ...]` (`kcal` null 가능)

### `GET /nutrition/{log_date}` — 하루 식단 상세

기록 없으면 404.

```json
{
  "profile_slug": "tteoni",
  "log_date": "2026-10-29",
  "logs": [
    {
      "log": { "id": 12, "profile_id": 1, "log_date": "2026-10-29", "meal_type": "아침",
               "food_name": "현미밥", "serving": "1공기", "sort_order": 0, "note": null },
      "values": { "kcal": 310, "carb": 68.5, "protein": 6.1 }
    }
  ],
  "totals": [
    { "nutrient_id": 1, "code": "kcal", "name_ko": "열량", "name_en": "Energy", "unit": "kcal",
      "category": "macro", "rda": 2200, "ul": null, "excess_warning": null,
      "sort_order": 0, "total": 1850 }
  ]
}
```

- `values` 는 `{영양소 code: 양}` 딕셔너리. 유효한 code 목록은 `GET /nutrients` 로 확인.
- `totals` 는 **전체 영양소 카탈로그 기준** — 오늘 안 먹은 영양소도 `total: 0` 으로 내려옴.
- `rda`/`ul` 은 프로필별 오버라이드가 있으면 그 값.

### `POST /nutrition/{log_date}/parse` — 자유 텍스트 식단 → 구조화 저장

Claude 가 텍스트를 파싱해 DB에 삽입. 서버에 yclaude 설정이 없으면 503.

| 필드 | 타입 | 필수 | 기본 | 설명 |
|---|---|---|---|---|
| `text` | string | ✔ | | 자유 서술 식단 ("아침에 현미밥 한 공기랑 계란 2개...") . 공백만이면 422 |
| `replace` | bool | | `false` | `true` = 그날 기존 기록 전부 삭제 후 저장, `false` = 뒤에 추가(append). append 시 기존 항목을 Claude 에 컨텍스트로 넘겨 중복 삽입을 방지 |

```bash
curl -X POST "http://127.0.0.1:8000/nutrition/2026-10-30/parse?profile=tteoni" \
  -H 'Content-Type: application/json' \
  -d '{"text": "점심 김치찌개 1인분, 공기밥 반 공기", "replace": false}'
```

응답:

```json
{
  "inserted": 2, "existing_before": 3, "total_after": 5, "mode": "append",
  "day": { "...": "GET /nutrition/{date} 와 동일한 전체 payload — 후속 조회 불필요" }
}
```

주의: LLM 호출이 포함되어 수 초 걸림 — 클라이언트 타임아웃을 넉넉히(30s+) 잡을 것.

### `GET /nutrients` — 영양소 카탈로그

파라미터 없음. `totals` 와 같은 구조에 `total: 0` 고정. `code` 값(예: `kcal`, `protein`,
`carb`, `fat`)을 여기서 확인해서 `values` 딕셔너리 키로 사용.

---

## 신체 둘레 기록 (`/body` 페이지)

체지방률·제지방 등 파생값은 클라이언트가 Navy 공식으로 계산하며 저장하지 않는다.

### `GET /body/records` — 전체 기록 (오래된 순)

응답 항목: 아래 쓰기 필드 + `record_date`.

### `PUT /body/records/{record_date}` — upsert

| 필드 | 타입 | 필수 | 기본 | 제약 |
|---|---|---|---|---|
| `sex` | string | | `"m"` | `"m"` 또는 `"f"` |
| `height_cm` | float | ✔ | | |
| `weight_kg` | float | ✔ | | |
| `neck_cm` | float | ✔ | | |
| `waist_cm` | float | ✔ | | |
| `hip_cm` | float | | null | **`sex:"f"` 이면 필수** (여성 공식에 사용) |
| `chest_cm` | float | | null | |
| `arm_cm` | float | | null | |
| `shoulder_cm` | float | | null | |
| `thigh_cm` | float | | null | |

```bash
curl -X PUT "http://127.0.0.1:8000/body/records/2026-10-30?profile=tteoni" \
  -H 'Content-Type: application/json' \
  -d '{"sex":"m","height_cm":187,"weight_kg":86.9,"neck_cm":40,"waist_cm":96}'
```

응답: 보낸 값 + `record_date`.

### `DELETE /body/records/{record_date}`

응답: `{"ok": true, "record_date": "2026-10-30"}` (없는 날짜여도 200 — 멱등).

---

## 주간 체중 기록

### `GET /weight/records` — 전체 (오래된 순)

### `PUT /weight/records/{record_date}` — upsert

| 필드 | 타입 | 필수 | 제약 |
|---|---|---|---|
| `weight_kg` | float | ✔ | 20 ~ 300 |
| `note` | string | | |

### `DELETE /weight/records/{record_date}`

---

## 인바디 기록

결과지의 인쇄값을 그대로 옮긴다. 단백질 목표·유지/감량 칼로리는 클라이언트 파생 계산.

### `GET /inbody/records` — 전체 (오래된 순)

### `PUT /inbody/records/{record_date}` / `POST /inbody` — upsert

두 엔드포인트는 동일 동작. `POST /inbody` 는 날짜를 바디의 `date` 필드로 받는
curl 친화 버전 (`{"date": "2026-10-30", ...나머지 동일}`).

| 필드 | 타입 | 필수 | 제약 |
|---|---|---|---|
| `weight_kg` | float | ✔ | > 0 |
| `skeletal_muscle_mass_kg` | float | ✔ | > 0 |
| `body_fat_mass_kg` | float | ✔ | 0 ≤ x < weight_kg |
| `percent_body_fat` | float | ✔ | 0 ~ 70 |
| `bmi` | float | | 10 ~ 60 |
| `lean_body_mass_kg` | float | | 0 < x ≤ weight_kg |
| `total_body_water_l` | float | | 0 < x ≤ weight_kg |
| `protein_kg` | float | | 0 < x < weight_kg |
| `minerals_kg` | float | | 0 < x < weight_kg |
| `visceral_fat_level` | int | | 1 ~ 30 |
| `waist_hip_ratio` | float | | 0.3 ~ 1.5 |
| `bmr_kcal` | int | | 500 ~ 4000 |
| `fat_control_kg` | float | | 음수 = 감량 권고 |
| `muscle_control_kg` | float | | 양수 = 증량 권고 |
| `inbody_score` | int | | 0 ~ 100 |
| `note` | string | | |

```bash
curl -X POST "http://127.0.0.1:8000/inbody?profile=tteoni" \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-10-30","weight_kg":86.9,"skeletal_muscle_mass_kg":33.9,
       "body_fat_mass_kg":25.9,"percent_body_fat":29.8,"bmr_kcal":1688}'
```

### `DELETE /inbody/records/{record_date}`

---

## 운동 기록 & 플랜

### `GET /workout/sessions` — 전체 세션 (오래된 순)

응답 항목: 아래 PUT 필드 + `session_date`.

### `PUT /workout/sessions/{session_date}` — upsert

세션 메타는 교체, **sets 는 통째로 교체** (보낸 목록이 그날의 전부가 됨).

| 필드 | 타입 | 필수 | 기본 | 제약 |
|---|---|---|---|---|
| `phase` | int | | 1 | `1`(머신 5종 적응기) 또는 `2`(7종 전신) |
| `discomfort` | int | | null | 세션 후 허리 불편감 0 ~ 10 |
| `note` | string | | null | |
| `sets` | array | | `[]` | 아래 WorkoutSet 배열 |

WorkoutSet:

| 필드 | 타입 | 필수 | 기본 | 제약 |
|---|---|---|---|---|
| `exercise` | string | ✔ | | 종목 슬러그 (부록 A) |
| `set_no` | int | ✔ | | 1 ~ 10. `(exercise, set_no)` 조합은 세션 내 유일해야 함 |
| `weight_kg` | float | | null | |
| `reps` | int | | null | |
| `skipped` | bool | | false | `true` = 수행 안 함 (집계·증량 판정 제외) |
| `skip_reason` | string | | null | `pain` \| `no_machine` \| `no_time`. **`skipped:true` 일 때만 보낼 수 있음** |

```bash
curl -X PUT "http://127.0.0.1:8000/workout/sessions/2026-10-30?profile=tteoni" \
  -H 'Content-Type: application/json' \
  -d '{
    "phase": 2, "discomfort": 1, "note": "어깨 컨디션 좋음",
    "sets": [
      {"exercise": "legpress",  "set_no": 1, "weight_kg": 80, "reps": 12},
      {"exercise": "legpress",  "set_no": 2, "weight_kg": 80, "reps": 12},
      {"exercise": "shoulderpress", "set_no": 1, "skipped": true, "skip_reason": "no_machine"}
    ]
  }'
```

### `DELETE /workout/sessions/{session_date}`

### `GET /workout/plan` — 다음 세션 처방 + 로드맵 (읽기 전용, 계산 결과)

세션 이력만으로 서버가 계산. 주요 응답 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `profile` | string | 슬러그 |
| `started` | string \| null | 첫 세션 날짜 |
| `sessions_total` | int | 누적 세션 수 |
| `program_week` | int \| null | 마지막 세션 기준 주차 |
| `phase` | int | 다음 세션에 적용할 단계 (1/2) |
| `phase1_done` / `phase1_target` | int | 1단계 진행도 |
| `hinge` | string \| null | 2단계 힙 힌지 종목 (`backext` \| `rdl`) |
| `caution` | string \| null | 허리 불편감 경고 등 |
| `next_session` | array | 종목별 처방 — `exercise, name, category, order, target_sets, target_reps_min/max, suggested_weight_kg, progression_due, progression_from_kg/to_kg, sessions_since_increase, volume_trend(up/flat/down), last_date, last_sets, note, guide_url` |
| `milestones` | array | `{key, title, period, detail, status(done/current/upcoming)}` |
| `rules` | string[] | 프로그램 규칙 설명 문장들 |

---

## 건강 노트 (RAG)

건강 특이사항을 **한 건 = 원자적 사실 하나**로 저장. `/notes/context` 가 전체를
LLM 프롬프트에 바로 주입 가능한 축약 텍스트로 변환해 준다.

### `GET /notes/records` — 노트 목록

| 쿼리 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `profile` | string | | |
| `category` | string | | 부록 B 의 8종 중 하나. 그 외 값은 422 |
| `q` | string | | 제목/내용/태그 부분 검색 (LIKE) |
| `include_archived` | bool | false | 보관 노트 포함 |

정렬: 보관 여부 → 고정(pinned) 먼저 → 최근 수정순.

응답 항목:

```json
{
  "id": 1, "category": "condition", "title": "요산 수치 경계",
  "content": "2024 검진 요산 7.2mg/dL(상한 7.0). 맥주·내장류 줄이는 중.",
  "tags": "요산,통풍,검진", "pinned": true, "archived": false,
  "updated_at": "2026-10-30 06:27:20"
}
```

### `POST /notes/records` — 생성 / `PUT /notes/records/{note_id}` — 수정

| 필드 | 타입 | 필수 | 기본 | 제약 |
|---|---|---|---|---|
| `category` | string | | `"other"` | 부록 B 의 8종 |
| `title` | string | ✔ | | 공백 불가, ≤ 120자 |
| `content` | string | ✔ | | 공백 불가, ≤ 1000자 — 축약된 사실 하나만 |
| `tags` | string | | null | 쉼표 구분 키워드 (`"요산,통풍"`) |
| `pinned` | bool | | false | 목록·컨텍스트 상단 고정 (★ 표시) |
| `archived` | bool | | false | `true` = 컨텍스트 생성에서 제외 (무효해진 사실은 삭제 대신 보관 권장) |

```bash
curl -X POST "http://127.0.0.1:8000/notes/records?profile=tteoni" \
  -H 'Content-Type: application/json' \
  -d '{"category":"allergy","title":"페니실린 계열 주의",
       "content":"어릴 때 페니실린 투여 후 두드러기 이력. 처방 전 고지 필요.",
       "tags":"항생제,알레르기","pinned":true}'
```

- PUT 은 전체 교체 — 모든 필드를 다시 보내야 함. 다른 프로필의 노트 id 면 404.
- 응답: 저장된 노트 객체 (서버가 채운 `id`, `updated_at` 포함).

### `DELETE /notes/records/{note_id}`

응답: `{"ok": true, "id": 3}` (멱등).

### `GET /notes/context` — RAG 컨텍스트 텍스트

| 쿼리 | 설명 |
|---|---|
| `profile` | |
| `category` | 특정 카테고리만 부분 컨텍스트로 |
| `q` | 검색 결과만 컨텍스트로 |

보관 노트는 항상 제외. 응답:

```json
{
  "profile_slug": "tteoni",
  "generated_at": "2026-10-30T06:30:00+00:00",
  "note_count": 2,
  "text": "[건강 노트 — 떠니 · 남성 · 1987년생 · 187cm]\n\n## 질환·진단\n- ★ 요산 수치 경계: 2024 검진 요산 7.2mg/dL(상한 7.0). ... #요산 #통풍\n\n## 알레르기·금기\n- 페니실린 계열 주의: ... #항생제"
}
```

`text` 를 그대로 LLM 시스템/유저 프롬프트에 붙이면 된다. 프로필 기본정보 헤더가
포함되어 이 텍스트 하나로 자기완결된다.

---

## 부록

### A. 운동 종목 슬러그 (`WorkoutSet.exercise`)

| 슬러그 | 이름 | 분류 |
|---|---|---|
| `legpress` | 레그프레스 | lower |
| `backext` | 백 익스텐션 | lower |
| `rdl` | 덤벨 RDL | lower |
| `legcurl` | 레그컬 | lower |
| `chestpress` | 체스트프레스 | upper |
| `shoulderpress` | 숄더프레스 | upper |
| `latpulldown` | 랫풀다운 | upper |
| `seatedrow` | 시티드 로우 | upper |

(DB 는 슬러그를 자유 텍스트로 받지만, 플랜 계산·프론트 표시는 위 8종 기준)

### B. 노트 카테고리 (`HealthNote.category`)

| 값 | 라벨 |
|---|---|
| `condition` | 질환·진단 |
| `medication` | 약물·보충제 |
| `allergy` | 알레르기·금기 |
| `symptom` | 증상·반응 |
| `lifestyle` | 생활·습관 |
| `family` | 가족력 |
| `goal` | 목표·계획 |
| `other` | 기타 |

### C. 상태값 모음

| 필드 | 값 |
|---|---|
| `Measurement.status` | `NORMAL` \| `LOW` \| `HIGH` \| null |
| `WorkoutSet.skip_reason` | `pain` \| `no_machine` \| `no_time` |
| `WorkoutPlanExercise.volume_trend` | `up` \| `flat` \| `down` |
| `WorkoutPlanMilestone.status` | `done` \| `current` \| `upcoming` |
| `NutritionParseResponse.mode` | `append` \| `replace` |
