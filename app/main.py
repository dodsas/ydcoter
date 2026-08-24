"""FastAPI server exposing health records over HTTP.

Run:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import (
    DB_PATH,
    TURSO_URL,
    connect,
    get_conn,
    get_local_conn,
    init_body_schema,
    init_health_schema,
    init_nutrition_schema,
    using_turso,
)
from app.models import (
    BodyRecord,
    BodyRecordIn,
    DailyNutrition,
    Measurement,
    NutrientTotal,
    NutritionDateSummary,
    NutritionLog,
    NutritionLogEntry,
    NutritionParseRequest,
    NutritionParseResponse,
    Profile,
    ReferenceUpdate,
    TestItem,
    Trend,
    TrendPoint,
    WorkoutSession,
    WorkoutSessionIn,
    WorkoutSet,
)
from app.nutrition_parser import parse_food_text
from app.yclaude_client import YClaudeError

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="ydocter",
    description="Personal health-checkup record API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "PATCH", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_schema() -> None:
    # Local: only init when the shipped data/health.db is absent (fresh
    # clones / volumes). In dev-fallback (no Turso), also apply the
    # nutrition schema so the same file can serve both roles.
    if not DB_PATH.exists():
        with get_local_conn() as conn:
            init_health_schema(conn)
            if not using_turso():
                init_nutrition_schema(conn)
                init_body_schema(conn)
    elif not using_turso():
        # Existing local DB in dev-fallback: body_records may not exist yet
        # (feature added after the DB was created) — idempotent, cheap.
        with get_local_conn() as conn:
            init_body_schema(conn)

    # Turso: idempotent — `CREATE TABLE IF NOT EXISTS` is cheap and keeps
    # the prod schema in sync with whatever ships in sql/schema-*.sql.
    if using_turso():
        with get_conn() as conn:
            init_nutrition_schema(conn)
            init_body_schema(conn)


# ===========================================================================
# Profile resolution helpers
# ===========================================================================


def _resolve_profile(conn, slug: Optional[str]) -> tuple[int, str]:
    """Return ``(id, slug)`` for the given slug, or fall back to the first profile.

    Returning both fields lets callers skip a follow-up ``SELECT slug ...``
    round-trip when they need the slug for the response payload.

    Raises 404 if the requested slug doesn't exist, or 400 if no profiles
    exist at all.
    """
    if slug:
        row = conn.execute(
            "SELECT id, slug FROM profiles WHERE slug = ?", (slug,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"profile '{slug}' not found")
        return row["id"], row["slug"]
    row = conn.execute(
        "SELECT id, slug FROM profiles ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    if not row:
        raise HTTPException(400, "no profiles defined — run `python -m app.load_data`")
    return row["id"], row["slug"]


def _resolve_profile_id(conn, slug: Optional[str]) -> int:
    """Backwards-compatible wrapper for callers that only need the id."""
    return _resolve_profile(conn, slug)[0]


# ===========================================================================
# Health / profiles
# ===========================================================================


@app.get("/health")
def healthcheck() -> dict:
    with get_local_conn() as conn:
        items = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
        measures = conn.execute("SELECT COUNT(*) AS n FROM measurements").fetchone()["n"]
        profiles = conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
    return {
        "status": "ok",
        "profiles": profiles,
        "items": items,
        "measurements": measures,
        "health_backend": "sqlite",
        "health_db": str(DB_PATH),
        "nutrition_backend": "turso" if using_turso() else "sqlite",
        "nutrition_db": TURSO_URL if using_turso() else str(DB_PATH),
    }


@app.get("/profiles", response_model=List[Profile])
def list_profiles() -> List[Profile]:
    with get_local_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id, p.slug, p.display_name, p.note, p.sort_order,
                p.sex, p.birth_year, p.height_cm,
                COUNT(DISTINCT i.id) AS item_count,
                COUNT(m.id)          AS measurement_count
            FROM profiles p
            LEFT JOIN test_items   i ON i.profile_id = p.id
            LEFT JOIN measurements m ON m.item_id    = i.id
            GROUP BY p.id, p.slug, p.display_name, p.note, p.sort_order,
                     p.sex, p.birth_year, p.height_cm
            ORDER BY p.sort_order, p.id
            """
        ).fetchall()
    return [Profile(**dict(r)) for r in rows]


# ===========================================================================
# Categories / items — scoped to a profile
# ===========================================================================


@app.get("/categories")
def categories(profile: Optional[str] = Query(None)) -> List[dict]:
    with get_local_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        rows = conn.execute(
            """
            SELECT major_category, minor_category, COUNT(*) AS item_count
            FROM test_items
            WHERE profile_id = ?
            GROUP BY major_category, minor_category
            ORDER BY major_category, minor_category
            """,
            (pid,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/items", response_model=List[TestItem])
def list_items(
    profile: Optional[str] = Query(None, description="프로필 슬러그"),
    major: Optional[str] = Query(None, description="대분류 필터"),
    minor: Optional[str] = Query(None, description="소분류 필터"),
    q: Optional[str] = Query(None, description="이름/코드 부분 검색"),
) -> List[TestItem]:
    with get_local_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        sql = "SELECT * FROM test_items WHERE profile_id = ?"
        params: list = [pid]
        if major:
            sql += " AND major_category = ?"
            params.append(major)
        if minor:
            sql += " AND minor_category = ?"
            params.append(minor)
        if q:
            sql += " AND (name LIKE ? OR code LIKE ?)"
            like = f"%{q}%"
            params += [like, like]
        sql += " ORDER BY major_category, minor_category, name"
        rows = conn.execute(sql, params).fetchall()
    return [TestItem(**dict(r)) for r in rows]


@app.get("/items/{item_id}", response_model=TestItem)
def get_item(item_id: int) -> TestItem:
    with get_local_conn() as conn:
        row = conn.execute(
            "SELECT * FROM test_items WHERE id = ?", (item_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"item {item_id} not found")
    return TestItem(**dict(row))


@app.get("/items/{item_id}/trend", response_model=Trend)
def item_trend(item_id: int) -> Trend:
    with get_local_conn() as conn:
        item_row = conn.execute(
            "SELECT * FROM test_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not item_row:
            raise HTTPException(404, f"item {item_id} not found")
        point_rows = conn.execute(
            """
            SELECT year, value_numeric, value_text, status
            FROM v_measurements
            WHERE item_id = ?
            ORDER BY year
            """,
            (item_id,),
        ).fetchall()
    return Trend(
        item=TestItem(**dict(item_row)),
        points=[TrendPoint(**dict(r)) for r in point_rows],
    )


@app.get("/measurements", response_model=List[Measurement])
def list_measurements(
    profile: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="NORMAL | LOW | HIGH"),
    major: Optional[str] = Query(None),
    minor: Optional[str] = Query(None),
) -> List[Measurement]:
    with get_local_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        sql = "SELECT * FROM v_measurements WHERE profile_id = ?"
        params: list = [pid]
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        if status:
            sql += " AND status = ?"
            params.append(status.upper())
        if major:
            sql += " AND major_category = ?"
            params.append(major)
        if minor:
            sql += " AND minor_category = ?"
            params.append(minor)
        sql += " ORDER BY year DESC, major_category, name"
        rows = conn.execute(sql, params).fetchall()
    return [Measurement(**dict(r)) for r in rows]


@app.get("/abnormal/{year}", response_model=List[Measurement])
def abnormal_for_year(
    year: int,
    profile: Optional[str] = Query(None),
) -> List[Measurement]:
    with get_local_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        rows = conn.execute(
            """
            SELECT * FROM v_measurements
            WHERE profile_id = ? AND year = ? AND status IN ('LOW', 'HIGH')
            ORDER BY major_category, name
            """,
            (pid, year),
        ).fetchall()
    return [Measurement(**dict(r)) for r in rows]


# ===========================================================================
# Nutrition
# ===========================================================================


@app.get("/nutrition/dates", response_model=List[NutritionDateSummary])
def nutrition_dates(profile: Optional[str] = Query(None)) -> List[NutritionDateSummary]:
    """List every date that has at least one logged food entry, newest first."""
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                l.log_date,
                COUNT(DISTINCT l.id) AS entry_count,
                COALESCE(
                    SUM(CASE WHEN n.code = 'kcal' THEN v.amount END),
                    0
                ) AS kcal
            FROM nutrition_logs l
            LEFT JOIN nutrition_values v ON v.log_id = l.id
            LEFT JOIN nutrients n        ON n.id = v.nutrient_id
            WHERE l.profile_id = ?
            GROUP BY l.log_date
            ORDER BY l.log_date DESC
            """,
            (pid,),
        ).fetchall()
    return [
        NutritionDateSummary(
            log_date=r["log_date"],
            entry_count=r["entry_count"],
            kcal=r["kcal"] or None,
        )
        for r in rows
    ]


@app.get("/nutrition/{log_date}", response_model=DailyNutrition)
def nutrition_for_day(
    log_date: str,
    profile: Optional[str] = Query(None),
) -> DailyNutrition:
    """Return all food entries + computed nutrient totals for a single day."""
    with get_local_conn() as lconn:
        pid, slug = _resolve_profile(lconn, profile)
    with get_conn() as conn:
        return _load_daily_nutrition(conn, pid, slug, log_date, require_data=True)


def _load_daily_nutrition(
    conn,
    profile_id: int,
    profile_slug: str,
    log_date: str,
    *,
    require_data: bool = False,
) -> DailyNutrition:
    """Shared loader for a single day's nutrition payload.

    ``require_data=True`` raises 404 when no entries exist; the parse
    endpoint passes False so it can return the freshly-inserted day.
    Callers pass ``profile_slug`` so this function can skip an extra
    round-trip just to resolve the slug from the id.
    """
    log_rows = conn.execute(
        """
        SELECT id, profile_id, log_date, meal_type, food_name, serving,
               sort_order, note
        FROM nutrition_logs
        WHERE profile_id = ? AND log_date = ?
        ORDER BY sort_order, id
        """,
        (profile_id, log_date),
    ).fetchall()

    if not log_rows and require_data:
        raise HTTPException(404, f"no nutrition logs for {log_date}")

    value_rows = conn.execute(
        """
        SELECT v.log_id, n.code, v.amount
        FROM nutrition_values v
        JOIN nutrients      n ON n.id = v.nutrient_id
        JOIN nutrition_logs l ON l.id = v.log_id
        WHERE l.profile_id = ? AND l.log_date = ?
        """,
        (profile_id, log_date),
    ).fetchall()

    # Drive from the full nutrients catalog so every tracked nutrient shows
    # up — even ones the user hasn't logged today. Missing rows surface as
    # total=0, which lets the frontend render the row and its "권장 식품"
    # hint instead of silently omitting it.
    totals_rows = conn.execute(
        """
        SELECT
            n.id                       AS nutrient_id,
            n.code                     AS code,
            n.name_ko,
            n.name_en,
            n.unit,
            n.category,
            COALESCE(po.rda, n.rda)    AS rda,
            COALESCE(po.ul,  n.ul)     AS ul,
            n.excess_warning,
            n.sort_order,
            COALESCE(daily.total, 0)   AS total
        FROM nutrients n
        LEFT JOIN profile_nutrient_rda po
            ON po.profile_id = ? AND po.nutrient_id = n.id
        LEFT JOIN (
            SELECT v.nutrient_id, SUM(v.amount) AS total
            FROM nutrition_values v
            JOIN nutrition_logs   l ON l.id = v.log_id
            WHERE l.profile_id = ? AND l.log_date = ?
            GROUP BY v.nutrient_id
        ) daily ON daily.nutrient_id = n.id
        ORDER BY n.sort_order
        """,
        (profile_id, profile_id, log_date),
    ).fetchall()

    values_by_log: dict[int, dict[str, float]] = {}
    for r in value_rows:
        values_by_log.setdefault(r["log_id"], {})[r["code"]] = r["amount"]

    logs = [
        NutritionLogEntry(
            log=NutritionLog(**dict(r)),
            values=values_by_log.get(r["id"], {}),
        )
        for r in log_rows
    ]
    totals = [NutrientTotal(**dict(r)) for r in totals_rows]

    return DailyNutrition(
        profile_slug=profile_slug,
        log_date=log_date,
        logs=logs,
        totals=totals,
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.post("/nutrition/{log_date}/parse", response_model=NutritionParseResponse)
def nutrition_parse(
    log_date: str,
    body: NutritionParseRequest,
    profile: Optional[str] = Query(None),
) -> NutritionParseResponse:
    """Parse a free-text food log via Claude and insert structured rows.

    Returns the resulting :class:`DailyNutrition` so the client can swap
    its view without a follow-up request.
    """
    if not _DATE_RE.match(log_date):
        raise HTTPException(422, "log_date must be ISO YYYY-MM-DD")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(422, "text is empty")

    settings = get_settings()
    if not settings.yclaude_enabled:
        raise HTTPException(
            503,
            "yclaude is not configured — set YCLAUDE_BASE_URL and YCLAUDE_API_KEY",
        )

    with get_local_conn() as lconn:
        pid, slug = _resolve_profile(lconn, profile)

    # Read phase. Close the libsql connection before the (slow) Claude
    # call — Turso/Hrana drops idle streams and the next query on the
    # same conn would 404 with "stream not found".
    with get_conn() as conn:
        catalog = [
            dict(r)
            for r in conn.execute(
                "SELECT id, code, name_ko, unit, category, rda, ul FROM nutrients ORDER BY sort_order"
            ).fetchall()
        ]
        nutrient_id_by_code = {row["code"]: row["id"] for row in catalog}

        # In append mode, hand the existing entries to Claude as context so
        # it won't re-emit them. In replace mode we still pass them — Claude
        # ignores the context once we delete + treat the new text as the
        # full day; but in practice we just clear the list to be safe.
        existing: list[dict] = []
        if not body.replace:
            existing = [
                dict(r) for r in conn.execute(
                    """
                    SELECT meal_type, food_name, serving
                    FROM nutrition_logs
                    WHERE profile_id = ? AND log_date = ?
                    ORDER BY sort_order, id
                    """,
                    (pid, log_date),
                ).fetchall()
            ]

    try:
        entries = parse_food_text(
            text,
            nutrient_catalog=catalog,
            date_iso=log_date,
            existing_entries=existing,
        )
    except YClaudeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    # Write phase. Fresh connection so we don't reuse a stream that may
    # have been recycled by Turso during the Claude round-trip.
    with get_conn() as conn:
        if body.replace:
            conn.execute(
                "DELETE FROM nutrition_logs WHERE profile_id = ? AND log_date = ?",
                (pid, log_date),
            )

        existing_max = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) AS m
            FROM nutrition_logs
            WHERE profile_id = ? AND log_date = ?
            """,
            (pid, log_date),
        ).fetchone()["m"]
        sort_order = existing_max + 1

        inserted = 0
        for entry in entries:
            cur = conn.execute(
                """
                INSERT INTO nutrition_logs
                  (profile_id, log_date, meal_type, food_name, serving, sort_order, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid, log_date, entry.meal, entry.food, entry.serving,
                    sort_order, entry.note,
                ),
            )
            log_id = cur.lastrowid
            for code, amount in entry.values.items():
                nutrient_id = nutrient_id_by_code.get(code)
                if nutrient_id is None:
                    continue
                conn.execute(
                    "INSERT INTO nutrition_values (log_id, nutrient_id, amount) VALUES (?, ?, ?)",
                    (log_id, nutrient_id, amount),
                )
            sort_order += 1
            inserted += 1

        conn.commit()
        day = _load_daily_nutrition(conn, pid, slug, log_date)

    return NutritionParseResponse(
        inserted=inserted,
        existing_before=len(existing),
        total_after=len(day.logs),
        mode="replace" if body.replace else "append",
        day=day,
    )


@app.get("/nutrients", response_model=List[NutrientTotal])
def list_nutrients() -> List[NutrientTotal]:
    """Catalog of tracked nutrients with RDA/UL — surfaces with zero totals."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id AS nutrient_id, code, name_ko, name_en, unit, category,
                   rda, ul, excess_warning, sort_order, 0 AS total
            FROM nutrients
            ORDER BY sort_order
            """
        ).fetchall()
    return [NutrientTotal(**dict(r)) for r in rows]


# ===========================================================================
# Body measurements (Navy-method tracker, /body page)
# ===========================================================================

_BODY_COLS = (
    "sex", "height_cm", "weight_kg", "neck_cm", "waist_cm",
    "hip_cm", "chest_cm", "arm_cm", "shoulder_cm", "thigh_cm",
)


@app.get("/body/records", response_model=List[BodyRecord])
def body_records(profile: Optional[str] = Query(None)) -> List[BodyRecord]:
    """All circumference records for a profile, oldest first (Day 0 first)."""
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT record_date, {", ".join(_BODY_COLS)}
            FROM body_records
            WHERE profile_id = ?
            ORDER BY record_date
            """,
            (pid,),
        ).fetchall()
    return [BodyRecord(**dict(r)) for r in rows]


@app.put("/body/records/{record_date}", response_model=BodyRecord)
def body_record_upsert(
    record_date: str,
    body: BodyRecordIn,
    profile: Optional[str] = Query(None),
) -> BodyRecord:
    """Insert or replace the record for one date (date = natural key)."""
    if not _DATE_RE.match(record_date):
        raise HTTPException(422, "record_date must be ISO YYYY-MM-DD")
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    values = [getattr(body, c) for c in _BODY_COLS]
    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO body_records (profile_id, record_date, {", ".join(_BODY_COLS)})
            VALUES ({", ".join("?" * (2 + len(_BODY_COLS)))})
            ON CONFLICT (profile_id, record_date) DO UPDATE SET
                {", ".join(f"{c} = excluded.{c}" for c in _BODY_COLS)}
            """,
            tuple([pid, record_date, *values]),
        )
        conn.commit()
    return BodyRecord(record_date=record_date, **body.model_dump())


@app.delete("/body/records/{record_date}")
def body_record_delete(
    record_date: str,
    profile: Optional[str] = Query(None),
) -> dict:
    if not _DATE_RE.match(record_date):
        raise HTTPException(422, "record_date must be ISO YYYY-MM-DD")
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM body_records WHERE profile_id = ? AND record_date = ?",
            (pid, record_date),
        )
        conn.commit()
    return {"ok": True, "record_date": record_date}


# ===========================================================================
# Workout sessions (machine program tracker, /workout page)
# ===========================================================================


@app.get("/workout/sessions", response_model=List[WorkoutSession])
def workout_sessions(profile: Optional[str] = Query(None)) -> List[WorkoutSession]:
    """All training sessions with their sets, oldest first."""
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        srows = conn.execute(
            """
            SELECT id, session_date, phase, discomfort, note
            FROM workout_sessions
            WHERE profile_id = ?
            ORDER BY session_date
            """,
            (pid,),
        ).fetchall()
        sets_by_session: dict[int, list[WorkoutSet]] = {}
        if srows:
            trows = conn.execute(
                """
                SELECT t.session_id, t.exercise, t.set_no, t.weight_kg, t.reps
                FROM workout_sets t
                JOIN workout_sessions s ON s.id = t.session_id
                WHERE s.profile_id = ?
                ORDER BY t.session_id, t.id
                """,
                (pid,),
            ).fetchall()
            for t in trows:
                sets_by_session.setdefault(t["session_id"], []).append(
                    WorkoutSet(
                        exercise=t["exercise"],
                        set_no=t["set_no"],
                        weight_kg=t["weight_kg"],
                        reps=t["reps"],
                    )
                )
    return [
        WorkoutSession(
            session_date=s["session_date"],
            phase=s["phase"],
            discomfort=s["discomfort"],
            note=s["note"],
            sets=sets_by_session.get(s["id"], []),
        )
        for s in srows
    ]


@app.put("/workout/sessions/{session_date}", response_model=WorkoutSession)
def workout_session_upsert(
    session_date: str,
    body: WorkoutSessionIn,
    profile: Optional[str] = Query(None),
) -> WorkoutSession:
    """Insert or replace the session for one date; sets are replaced wholesale."""
    if not _DATE_RE.match(session_date):
        raise HTTPException(422, "session_date must be ISO YYYY-MM-DD")
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO workout_sessions (profile_id, session_date, phase, discomfort, note)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (profile_id, session_date) DO UPDATE SET
                phase = excluded.phase,
                discomfort = excluded.discomfort,
                note = excluded.note
            """,
            (pid, session_date, body.phase, body.discomfort, body.note),
        )
        sid = conn.execute(
            "SELECT id FROM workout_sessions WHERE profile_id = ? AND session_date = ?",
            (pid, session_date),
        ).fetchone()["id"]
        conn.execute("DELETE FROM workout_sets WHERE session_id = ?", (sid,))
        for s in body.sets:
            conn.execute(
                """
                INSERT INTO workout_sets (session_id, exercise, set_no, weight_kg, reps)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, s.exercise, s.set_no, s.weight_kg, s.reps),
            )
        conn.commit()
    return WorkoutSession(session_date=session_date, **body.model_dump())


@app.delete("/workout/sessions/{session_date}")
def workout_session_delete(
    session_date: str,
    profile: Optional[str] = Query(None),
) -> dict:
    if not _DATE_RE.match(session_date):
        raise HTTPException(422, "session_date must be ISO YYYY-MM-DD")
    with get_local_conn() as lconn:
        pid = _resolve_profile_id(lconn, profile)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM workout_sessions WHERE profile_id = ? AND session_date = ?",
            (pid, session_date),
        ).fetchone()
        if row:
            # explicit set delete — FK cascade needs PRAGMA foreign_keys,
            # which the Turso path doesn't guarantee
            conn.execute("DELETE FROM workout_sets WHERE session_id = ?", (row["id"],))
            conn.execute("DELETE FROM workout_sessions WHERE id = ?", (row["id"],))
            conn.commit()
    return {"ok": True, "session_date": session_date}


# ===========================================================================
# Reference editing
# ===========================================================================


@app.patch("/items/{item_id}/reference", response_model=TestItem)
def update_reference(item_id: int, body: ReferenceUpdate) -> TestItem:
    """Update the clinical reference range for a single indicator.

    The v_measurements view recomputes status (HIGH/LOW/NORMAL) dynamically,
    so updates take effect on the next read without re-seeding.

    Fields explicitly omitted from the payload are left unchanged. Sending
    `null` for a field clears that bound.
    """
    sent = body.model_fields_set
    with get_local_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM test_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, f"item {item_id} not found")

        new_min = body.ref_min if "ref_min" in sent else existing["ref_min"]
        new_max = body.ref_max if "ref_max" in sent else existing["ref_max"]
        new_ind = (
            body.ref_indicator if "ref_indicator" in sent else existing["ref_indicator"]
        )
        if isinstance(new_ind, str) and not new_ind.strip():
            new_ind = None

        if (
            new_min is not None
            and new_max is not None
            and new_min > new_max
        ):
            raise HTTPException(422, "ref_min must be ≤ ref_max")

        conn.execute(
            "UPDATE test_items SET ref_min = ?, ref_max = ?, ref_indicator = ? WHERE id = ?",
            (new_min, new_max, new_ind, item_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM test_items WHERE id = ?", (item_id,)
        ).fetchone()

    global _REFERENCE_EPOCH
    _REFERENCE_EPOCH += 1

    return TestItem(**dict(row))


# ===========================================================================
# Static dashboard
# ===========================================================================
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


def _resolve_commit() -> str:
    # Render exposes RENDER_GIT_COMMIT; locally we read from .git.
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    if commit:
        return commit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(WEB_DIR.parent),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return ""


_GIT_COMMIT = _resolve_commit()
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

# Bumped whenever a reference value is edited — the dashboard cache on the
# client keys its localStorage entries off `data_version`, so a bump
# invalidates every cached payload on the next load.
_REFERENCE_EPOCH = 0


def _data_version() -> str:
    short = _GIT_COMMIT[:7] if _GIT_COMMIT else "dev"
    return f"{short}.{_REFERENCE_EPOCH}"


@app.get("/version", include_in_schema=False)
def version() -> dict:
    return {
        "commit": _GIT_COMMIT,
        "commit_short": _GIT_COMMIT[:7] if _GIT_COMMIT else "",
        "deployed_at": _STARTED_AT,
        "data_version": _data_version(),
    }


def _render_html(name: str) -> HTMLResponse:
    # Substitute {{V}} with data_version so cached `?v=…` URLs invalidate
    # whenever a new build (or reference edit) ships.
    html = (WEB_DIR / name).read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{V}}", _data_version()))


@app.get("/", include_in_schema=False)
def root() -> HTMLResponse:
    # 메인 페이지 = 운동 기록 (영양은 /nutrition 으로)
    return _render_html("workout.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> HTMLResponse:
    return _render_html("index.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> HTMLResponse:
    return _render_html("settings.html")


@app.get("/nutrition", include_in_schema=False)
def nutrition_page() -> HTMLResponse:
    return _render_html("nutrition.html")


@app.get("/body", include_in_schema=False)
def body_page() -> HTMLResponse:
    return _render_html("body.html")


@app.get("/workout", include_in_schema=False)
def workout_page() -> HTMLResponse:
    return _render_html("workout.html")
