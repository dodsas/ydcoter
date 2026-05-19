"""FastAPI server exposing health records over HTTP.

Run:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import DB_PATH, get_conn, init_schema, connect
from app.models import Measurement, ReferenceUpdate, TestItem, Trend, TrendPoint

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="ydocter",
    description="Personal health-checkup record API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "PATCH"],
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


@app.get("/health")
def healthcheck() -> dict:
    with get_conn() as conn:
        items = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
        measures = conn.execute("SELECT COUNT(*) AS n FROM measurements").fetchone()["n"]
    return {"status": "ok", "items": items, "measurements": measures, "db": str(DB_PATH)}


@app.get("/categories")
def categories() -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT major_category, minor_category, COUNT(*) AS item_count
            FROM test_items
            GROUP BY major_category, minor_category
            ORDER BY major_category, minor_category
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/items", response_model=List[TestItem])
def list_items(
    major: Optional[str] = Query(None, description="대분류 필터"),
    minor: Optional[str] = Query(None, description="소분류 필터"),
    q: Optional[str] = Query(None, description="이름/코드 부분 검색"),
) -> List[TestItem]:
    sql = "SELECT * FROM test_items WHERE 1=1"
    params: list = []
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
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TestItem(**dict(r)) for r in rows]


@app.get("/items/{item_id}", response_model=TestItem)
def get_item(item_id: int) -> TestItem:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM test_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"item {item_id} not found")
    return TestItem(**dict(row))


@app.get("/items/{item_id}/trend", response_model=Trend)
def item_trend(item_id: int) -> Trend:
    with get_conn() as conn:
        item_row = conn.execute("SELECT * FROM test_items WHERE id = ?", (item_id,)).fetchone()
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
    year: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="NORMAL | LOW | HIGH"),
    major: Optional[str] = Query(None),
    minor: Optional[str] = Query(None),
) -> List[Measurement]:
    sql = "SELECT * FROM v_measurements WHERE 1=1"
    params: list = []
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
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [Measurement(**dict(r)) for r in rows]


@app.get("/abnormal/{year}", response_model=List[Measurement])
def abnormal_for_year(year: int) -> List[Measurement]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM v_measurements
            WHERE year = ? AND status IN ('LOW', 'HIGH')
            ORDER BY major_category, name
            """,
            (year,),
        ).fetchall()
    return [Measurement(**dict(r)) for r in rows]


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
        # Normalize empty string to NULL for the text indicator.
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


# ---- Static dashboard ----
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(str(WEB_DIR / "settings.html"))
