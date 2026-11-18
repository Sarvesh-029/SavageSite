from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.audit import Category, Severity


class Penalty(BaseModel):
    issue_id: str
    severity: Severity
    points: int


class CategoryScore(BaseModel):
    score: int | float | None
    status: Literal["ok", "unavailable"]
    original_weight: float
    effective_weight: float
    penalties: list[Penalty]


class ExcludedCategory(BaseModel):
    category: Category
    reason: str


class ScoreBreakdown(BaseModel):
    categories: dict[Category, CategoryScore]
    overall_score: int | None
    excluded_categories: list[ExcludedCategory]
    low_confidence: bool
    health_label: Literal["Healthy", "Decent", "Needs work", "Critical"] | None
    scoring_version: str
