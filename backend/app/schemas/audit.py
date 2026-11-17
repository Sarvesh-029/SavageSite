from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["performance", "ui_ux", "responsiveness", "seo", "accessibility"]
Severity = Literal["critical", "high", "medium", "low"]
Source = Literal["lighthouse", "axe", "dom", "vision"]
Confidence = Literal["measured", "heuristic"]


class Issue(BaseModel):
    id: str
    category: Category
    severity: Severity
    title: str
    description: str
    evidence: list[str] = Field(min_length=1)
    impact: str
    recommendation: str
    source: Source
    confidence: Confidence


class Strength(BaseModel):
    id: str
    category: Category
    title: str
    description: str
    evidence: list[str] = Field(min_length=1)


class CheckResult(BaseModel):
    status: Literal["ok", "unavailable"]
    reason: str | None = None
    issues: list[Issue] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class AuditFindings(BaseModel):
    scan: Any
    issues: list[Issue] = Field(default_factory=list)
    strengths: list[Strength] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    category_status: dict[Category, CheckResult] = Field(default_factory=dict)
