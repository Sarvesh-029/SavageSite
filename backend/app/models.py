from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Audit(Base):
    __tablename__ = "audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    website_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    website_title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    health_label: Mapped[str | None] = mapped_column(String(20))
    low_confidence: Mapped[bool | None] = mapped_column(Boolean)
    scan_json: Mapped[dict | None] = mapped_column(JSON)
    metrics_json: Mapped[dict | None] = mapped_column(JSON)
    strengths_json: Mapped[list | None] = mapped_column(JSON)
    scoring_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issues: Mapped[list["AuditIssue"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    category_scores: Mapped[list["CategoryScoreRow"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class AuditIssue(Base):
    __tablename__ = "audit_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    issue_id: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list] = mapped_column(JSON)
    impact: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[str] = mapped_column(String(20))


class CategoryScoreRow(Base):
    __tablename__ = "category_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    original_weight: Mapped[float] = mapped_column(Float)
    effective_weight: Mapped[float] = mapped_column(Float)
