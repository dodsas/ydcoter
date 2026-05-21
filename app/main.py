"""FastAPI server exposing health records over HTTP.

Run:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import DB_PATH, connect, get_conn, init_schema
from app.models import (
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
    allow_methods=["GET", "PATCH", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_schema() -> None:
    if not DB_PATH.exists():
        conn = connect()
        try:
            init_schema(conn)
            conn.commit()
        finally:
            conn.close()


# ===========================================================================
# Profile resolution helpers
# ===========================================================================


def _resolve_profile_id(conn, slug: Optional[str]) -> int:
    """Return the row id for the given slug, or fall back to the first profile.

    Raises 404 if the requested slug doesn't exist, or 400 if no profiles
    exist at all.
    """
    if slug:
        row = conn.execute(
            "SELECT id FROM profiles WHERE slug = ?", (slug,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"profile '{slug}' not found")
        return row["id"]
    row = conn.execute(
        "SELECT id FROM profiles ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    if not row:
        raise HTTPException(400, "no profiles defined — run `python -m app.load_data`")
    return row["id"]


# ===========================================================================
# Health / profiles
# ===========================================================================


@app.get("/health")
def healthcheck() -> dict:
    with get_conn() as conn:
        items = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
        measures = conn.execute("SELECT COUNT(*) AS n FROM measurements").fetchone()["n"]
        profiles = conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"]
    return {
        "status": "ok",
        "profiles": profiles,
        "items": items,
        "measurements": measures,
        "db": str(DB_PATH),
    }


@app.get("/profiles", response_model=List[Profile])
def list_profiles() -> List[Profile]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id, p.slug, p.display_name, p.note, p.sort_order,
                p.sex, p.birth_year, p.height_cm,
                (SELECT COUNT(*) FROM test_items i WHERE i.profile_id = p.id) AS item_count,
                (SELECT COUNT(*) FROM measurements m
                   JOIN test_items i ON i.id = m.item_id
                   WHERE i.profile_id = p.id) AS measurement_count
            FROM profiles p
            ORDER BY p.sort_order, p.id
            """
        ).fetchall()
    return [Profile(**dict(r)) for r in rows]


# ===========================================================================
# Categories / items — scoped to a profile
# ===========================================================================


@app.get("/categories")
def categories(profile: Optional[str] = Query(None)) -> List[dict]:
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM test_items WHERE id = ?", (item_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"item {item_id} not found")
    return TestItem(**dict(row))


@app.get("/items/{item_id}/trend", response_model=Trend)
def item_trend(item_id: int) -> Trend:
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
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
    with get_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        rows = conn.execute(
            """
            SELECT
                l.log_date,
                COUNT(DISTINCT l.id) AS entry_count,
                (
                    SELECT COALESCE(SUM(v2.amount), 0)
                    FROM nutrition_values v2
                    JOIN nutrients n2 ON n2.id = v2.nutrient_id
                    WHERE n2.code = 'kcal'
                      AND v2.log_id IN (
                          SELECT id FROM nutrition_logs
                          WHERE profile_id = ? AND log_date = l.log_date
                      )
                ) AS kcal
            FROM nutrition_logs l
            WHERE l.profile_id = ?
            GROUP BY l.log_date
            ORDER BY l.log_date DESC
            """,
            (pid, pid),
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
    with get_conn() as conn:
        pid = _resolve_profile_id(conn, profile)
        return _load_daily_nutrition(conn, pid, log_date, require_data=True)


def _load_daily_nutrition(
    conn,
    profile_id: int,
    log_date: str,
    *,
    require_data: bool = False,
) -> DailyNutrition:
    """Shared loader for a single day's nutrition payload.

    ``require_data=True`` raises 404 when no entries exist; the parse
    endpoint passes False so it can return the freshly-inserted day.
    """
    profile_slug = conn.execute(
        "SELECT slug FROM profiles WHERE id = ?", (profile_id,)
    ).fetchone()["slug"]

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
        JOIN nutrients        n ON n.id = v.nutrient_id
        WHERE v.log_id IN (
            SELECT id FROM nutrition_logs
            WHERE profile_id = ? AND log_date = ?
        )
        """,
        (profile_id, log_date),
    ).fetchall()

    totals_rows = conn.execute(
        """
        SELECT nutrient_id, nutrient_code AS code, name_ko, name_en,
               unit, category, rda, ul, sort_order, total
        FROM v_daily_nutrition
        WHERE profile_id = ? AND log_date = ?
        ORDER BY sort_order
        """,
        (profile_id, log_date),
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

    with get_conn() as conn:
        pid = _resolve_profile_id(conn, profile)

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
        day = _load_daily_nutrition(conn, pid, log_date)

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
                   rda, ul, sort_order, 0 AS total
            FROM nutrients
            ORDER BY sort_order
            """
        ).fetchall()
    return [NutrientTotal(**dict(r)) for r in rows]


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
    with get_conn() as conn:
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
    return TestItem(**dict(row))


# ===========================================================================
# Static dashboard
# ===========================================================================
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(str(WEB_DIR / "settings.html"))


@app.get("/nutrition", include_in_schema=False)
def nutrition_page() -> FileResponse:
    return FileResponse(str(WEB_DIR / "nutrition.html"))
