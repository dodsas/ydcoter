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


class BodyRecordIn(BaseModel):
    """Upsert payload for one day's body-circumference measurement.

    Body fat % / lean mass / FFMI are derived client-side (Navy method)
    and intentionally not stored.
    """

    sex: str = "m"  # 'm' | 'f' — female formula additionally needs hip_cm
    height_cm: float
    weight_kg: float
    neck_cm: float
    waist_cm: float
    hip_cm: Optional[float] = None
    chest_cm: Optional[float] = None
    arm_cm: Optional[float] = None
    shoulder_cm: Optional[float] = None
    thigh_cm: Optional[float] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self):
        if self.sex not in ("m", "f"):
            raise ValueError("sex must be 'm' or 'f'")
        if self.sex == "f" and self.hip_cm is None:
            raise ValueError("hip_cm is required for the female formula")
        return self


class BodyRecord(BodyRecordIn):
    record_date: str


class WeightRecordIn(BaseModel):
    """Upsert payload for one weekly weigh-in (weight only)."""

    weight_kg: float
    note: Optional[str] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self):
        if not 20 <= self.weight_kg <= 300:
            raise ValueError("weight_kg must be 20..300")
        return self


class WeightRecord(WeightRecordIn):
    record_date: str


class InbodyRecordIn(BaseModel):
    """Upsert payload for one InBody measurement (transcribed from the sheet).

    필드명은 결과지의 공식 영문 표기(SMM, PBF, WHR ...)를 따른다.
    단백질 목표 / 유지·감량 칼로리는 클라이언트에서 파생 계산하며 저장하지
    않는다. lean_body_mass_kg 는 결과지에 인쇄된 값이 있으면 저장하고,
    없으면 클라이언트가 체중 − 체지방량으로 대체 계산한다.
    """

    weight_kg: float
    skeletal_muscle_mass_kg: float
    body_fat_mass_kg: float
    percent_body_fat: float
    bmi: Optional[float] = None
    lean_body_mass_kg: Optional[float] = None
    total_body_water_l: Optional[float] = None
    protein_kg: Optional[float] = None
    minerals_kg: Optional[float] = None
    visceral_fat_level: Optional[int] = None
    waist_hip_ratio: Optional[float] = None
    bmr_kcal: Optional[int] = None
    fat_control_kg: Optional[float] = None
    muscle_control_kg: Optional[float] = None
    inbody_score: Optional[int] = None
    note: Optional[str] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self):
        if self.weight_kg <= 0:
            raise ValueError("weight_kg must be > 0")
        if self.skeletal_muscle_mass_kg <= 0:
            raise ValueError("skeletal_muscle_mass_kg must be > 0")
        if not 0 <= self.body_fat_mass_kg < self.weight_kg:
            raise ValueError("body_fat_mass_kg must be 0 ≤ x < weight_kg")
        if not 0 <= self.percent_body_fat < 70:
            raise ValueError("percent_body_fat must be 0..70")
        if self.bmi is not None and not 10 <= self.bmi <= 60:
            raise ValueError("bmi must be 10..60")
        if self.lean_body_mass_kg is not None and not 0 < self.lean_body_mass_kg <= self.weight_kg:
            raise ValueError("lean_body_mass_kg must be 0 < x ≤ weight_kg")
        if self.total_body_water_l is not None and not 0 < self.total_body_water_l <= self.weight_kg:
            raise ValueError("total_body_water_l must be 0 < x ≤ weight_kg")
        if self.protein_kg is not None and not 0 < self.protein_kg < self.weight_kg:
            raise ValueError("protein_kg must be 0 < x < weight_kg")
        if self.minerals_kg is not None and not 0 < self.minerals_kg < self.weight_kg:
            raise ValueError("minerals_kg must be 0 < x < weight_kg")
        if self.visceral_fat_level is not None and not 1 <= self.visceral_fat_level <= 30:
            raise ValueError("visceral_fat_level must be 1..30")
        if self.waist_hip_ratio is not None and not 0.3 <= self.waist_hip_ratio <= 1.5:
            raise ValueError("waist_hip_ratio must be 0.3..1.5")
        if self.bmr_kcal is not None and not 500 <= self.bmr_kcal <= 4000:
            raise ValueError("bmr_kcal must be 500..4000")
        if self.inbody_score is not None and not 0 <= self.inbody_score <= 100:
            raise ValueError("inbody_score must be 0..100")
        return self


class InbodyRecordCreate(InbodyRecordIn):
    """POST /inbody payload — the measurement date rides in the body."""

    date: str  # ISO YYYY-MM-DD


class InbodyRecord(InbodyRecordIn):
    record_date: str


class WorkoutSet(BaseModel):
    """One set of one exercise within a session."""

    exercise: str  # slug: legpress, chestpress, latpulldown, ...
    set_no: int
    weight_kg: Optional[float] = None
    reps: Optional[int] = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self):
        if not self.exercise.strip():
            raise ValueError("exercise must not be empty")
        if not 1 <= self.set_no <= 10:
            raise ValueError("set_no must be 1..10")
        return self


class WorkoutSessionIn(BaseModel):
    """Upsert payload for one training session (date = natural key)."""

    phase: int = 1  # 1: 머신 5종 적응기, 2: 7종 전신
    discomfort: Optional[int] = None  # 세션 후 허리 불편감 0~10
    note: Optional[str] = None
    sets: List[WorkoutSet] = []

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self):
        if self.phase not in (1, 2):
            raise ValueError("phase must be 1 or 2")
        if self.discomfort is not None and not 0 <= self.discomfort <= 10:
            raise ValueError("discomfort must be 0..10")
        return self


class WorkoutSession(WorkoutSessionIn):
    session_date: str
