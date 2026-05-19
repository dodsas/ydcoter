# ydocter

개인 건강검진 기록을 보관·조회하는 가벼운 로컬 서버.

- **DB**: SQLite (단일 파일, WAL 모드)
- **API**: FastAPI + Uvicorn
- **데이터 영속성**: `data/health.db` 파일 (서버 재시작 무관)

## 구조

```
ydocter/
├── app/
│   ├── database.py     # SQLite 커넥션
│   ├── load_data.py    # 시드 적재 스크립트
│   ├── seed_data.py    # 검진 데이터 (편집 가능)
│   ├── models.py       # Pydantic 모델
│   └── main.py         # FastAPI 엔드포인트
├── sql/
│   └── schema.sql      # 스키마 + 뷰
├── data/
│   └── health.db       # ← 실 데이터 (gitignored)
└── requirements.txt
```

## 설치 & 실행

```bash
# 가상환경 + 의존성
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. DB 초기화 & 시드 적재
python -m app.load_data

# 2. 서버 기동
uvicorn app.main:app --reload
# → http://localhost:8000/docs  (Swagger UI)
```

## 주요 엔드포인트

| 메소드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | DB 연결/항목 수 확인 |
| `GET` | `/categories` | 대/소분류 목록 |
| `GET` | `/items` | 항목 검색 (`?major=&minor=&q=`) |
| `GET` | `/items/{id}` | 항목 상세 |
| `GET` | `/items/{id}/trend` | 연도별 추이 + 정상/이상 판정 |
| `GET` | `/measurements` | 측정값 필터 (`?year=&status=LOW|HIGH|NORMAL`) |
| `GET` | `/abnormal/{year}` | 특정 연도의 이상 수치만 |

## 데이터 갱신

- `app/seed_data.py` 의 `RECORDS` 리스트를 직접 수정
- `python -m app.load_data` 재실행 (기본은 `--reset` → 전체 재적재)
- `python -m app.load_data --keep` 옵션은 스키마만 보장하고 데이터는 보존

## SQL 직접 조회

```bash
sqlite3 data/health.db
sqlite> SELECT year, value_numeric, status
        FROM v_measurements
        WHERE name = 'BMI'
        ORDER BY year;
```
