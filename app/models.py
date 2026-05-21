"""Pydantic schemas for the FastAPI layer."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, model_validator


class Profile(BaseModel):
    id: int
    slug: str
    display_name: str
    note: Optional[str] = None
    sort_order: int = 0
    sex: Optional[str] = None
    birth_year: Optional[int] = None
    height_cm: Optional[float] = None
    item_count: int = 0
    measurement_count: int = 0


class TestItem(BaseModel):
    id: int
    profile_id: int
    major_category: str
    minor_category: str
    code: Optional[str] = None
    name: str
    unit: Optional[str] = None
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    ref_indicator: Optional[str] = None
    related_diseases: Optional[str] = None
    memo: Optional[str] = None


class Measurement(BaseModel):
    measurement_id: int
    item_id: int
    profile_id: int
    profile_slug: str
    year: int
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    status: Optional[str] = None  # NORMAL | LOW | HIGH | None


class TrendPoint(BaseModel):
    year: int
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    status: Optional[str] = None


class Trend(BaseModel):
    item: TestItem
    points: List[TrendPoint]


class NutritionLog(BaseModel):
    id: int
    profile_id: int
    log_date: str
    meal_type: str
    food_name: str
    serving: Optional[str] = None
    sort_order: int = 0
    note: Optional[str] = None


class NutritionLogEntry(BaseModel):
    log: NutritionLog
    values: dict  # { nutrient_code: amount }


class NutrientTotal(BaseModel):
    nutrient_id: int
    code: str
    name_ko: str
    name_en: Optional[str] = None
    unit: str
    category: str
    rda: Optional[float] = None
    ul: Optional[float] = None
    excess_warning: Optional[str] = None
    sort_order: int = 0
    total: float


class DailyNutrition(BaseModel):
    profile_slug: str
    log_date: str
    logs: List[NutritionLogEntry]
    totals: List[NutrientTotal]


class NutritionDateSummary(BaseModel):
    log_date: str
    entry_count: int
    kcal: Optional[float] = None


class NutritionParseRequest(BaseModel):
    """Free-text food log to be parsed by Claude.

    ``replace`` deletes any existing entries for the date first — the
    common case when the user revises a day. Default is False so a user
    can accumulate entries across multiple submissions.
    """
    text: str
    replace: bool = False
    model_config = {"extra": "forbid"}


class NutritionParseResponse(BaseModel):
    inserted: int
    existing_before: int
    total_after: int
    mode: str                 # 'append' | 'replace'
    day: DailyNutrition


class ReferenceUpdate(BaseModel):
    """Patch payload for clinical reference range edits.

    All fields are optional and nullable — sending `null` explicitly clears
    the bound. Omitting a field leaves it unchanged.
    """

    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    ref_indicator: Optional[str] = None

    # marker so we can distinguish "omitted" vs "explicit null" client-side;
    # FastAPI exposes this via `model_fields_set`.
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_bounds(self):
        if (
            self.ref_min is not None
            and self.ref_max is not None
            and self.ref_min > self.ref_max
        ):
            raise ValueError("ref_min must be ≤ ref_max")
        return self
