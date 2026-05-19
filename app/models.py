"""Pydantic schemas for the FastAPI layer."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, model_validator


class TestItem(BaseModel):
    id: int
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
