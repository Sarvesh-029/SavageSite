from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, Field


class DesignCrime(BaseModel):
    issue_id: str = Field(max_length=200)
    roast: str = Field(max_length=280)


class CategoryRoasts(BaseModel):
    performance: str | None = Field(default=None, max_length=400)
    mobile: str | None = Field(default=None, max_length=400)
    seo: str | None = Field(default=None, max_length=400)
    accessibility: str | None = Field(default=None, max_length=400)


class Weakness(BaseModel):
    issue_id: str = Field(max_length=200)
    explanation: str = Field(max_length=400)


class IssueExplanation(BaseModel):
    issue_id: str = Field(max_length=200)
    plain_explanation: str = Field(max_length=500)


class RoadmapItem(BaseModel):
    issue_id: str = Field(max_length=200)
    action: str = Field(max_length=400)


class Roadmap(BaseModel):
    fix_immediately: list[RoadmapItem] = Field(max_length=10)
    fix_soon: list[RoadmapItem] = Field(max_length=10)
    long_term: list[RoadmapItem] = Field(max_length=10)


class StrengthCommentary(BaseModel):
    strength_id: str = Field(max_length=200)
    comment: str = Field(max_length=300)


class RoastOutput(BaseModel):
    overall_roast: str = Field(max_length=800)
    design_crimes: list[DesignCrime] = Field(max_length=3)
    category_roasts: CategoryRoasts
    top_weaknesses: list[Weakness] = Field(max_length=3)
    issue_explanations: list[IssueExplanation] = Field(max_length=25)
    roadmap: Roadmap
    strengths_commentary: list[StrengthCommentary] = Field(max_length=10)
    final_verdict: str = Field(max_length=500)
    visual_observations: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=5)


Intensity = Literal["mild", "brutal", "nuclear"]
