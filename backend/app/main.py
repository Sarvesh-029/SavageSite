from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Audit, AuditIssue, AuditRoast
from app.schemas.roast import Intensity
from app.services.ai_service import generate_roast


def _roast_reason(code: str | None) -> str | None:
    return {"ai_not_configured": "AI is not configured", "ai_unavailable": "AI is temporarily unavailable",
            "ai_timeout": "AI request timed out", "ai_rate_limited": "AI is rate limited",
            "ai_invalid_output": "AI returned an invalid response"}.get(code)
from app.services.audit_runner import STAGES, recover_orphans, run_audit
from app.services.scanner import STORAGE_ROOT
from app.utils.url_validator import URLValidationError, validate_url


class CreateAuditRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class CreateAuditResponse(BaseModel):
    audit_id: str
    status: str
    status_url: str


class RoastRequest(BaseModel):
    intensity: Intensity
    regenerate: bool = False


class StatusError(BaseModel):
    code: str
    message: str


class AuditStatus(BaseModel):
    status: str
    stage: str
    stage_index: int
    total_stages: int
    error: StatusError | None = None


app = FastAPI(title="SavageSite API")
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    app.add_middleware(CORSMiddleware, allow_origins=[frontend_url], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])
_rate_lock = threading.Lock()
_requests: dict[str, deque[float]] = defaultdict(deque)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)
    recover_orphans()


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _limited(ip: str) -> bool:
    limit = max(1, int(os.getenv("RATE_LIMIT_PER_HOUR", "10")))
    now = datetime.now(timezone.utc).timestamp()
    with _rate_lock:
        timestamps = _requests[ip]
        while timestamps and timestamps[0] <= now - 3600:
            timestamps.popleft()
        if len(timestamps) >= limit:
            return True
        timestamps.append(now)
        return False


def _insert_audit(audit_id: str, url: str) -> None:
    with SessionLocal() as db:
        db.add(Audit(id=audit_id, website_url=url, status="queued", stage="initializing", stage_index=1))
        db.commit()


@app.post("/api/audits", response_model=CreateAuditResponse, status_code=202)
async def create_audit(body: CreateAuditRequest, request: Request, background_tasks: BackgroundTasks):
    ip = request.client.host if request.client else "unknown"
    if _limited(ip):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many audits have been requested. Try again later."})
    try:
        await validate_url(body.url)
    except URLValidationError as exc:
        code = "blocked_target" if exc.code == "blocked_target" else "invalid_url"
        raise HTTPException(status_code=422, detail={"code": code, "message": exc.safe_message}) from None
    audit_id = str(uuid.uuid4())
    await asyncio.to_thread(_insert_audit, audit_id, body.url)
    background_tasks.add_task(run_audit, audit_id)
    return CreateAuditResponse(audit_id=audit_id, status="queued", status_url=f"/api/audits/{audit_id}/status")


def _validated_id(audit_id: str) -> str:
    try:
        return str(uuid.UUID(audit_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Audit not found."}) from None


def _status(row: Audit) -> dict:
    error = {"code": row.error_code, "message": row.error_message} if row.error_code else None
    return {"status": row.status, "stage": row.stage, "stage_index": row.stage_index, "total_stages": len(STAGES), "error": error}


@app.get("/api/audits/{audit_id}/status", response_model=AuditStatus)
def get_status(audit_id: str):
    audit_id = _validated_id(audit_id)
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Audit not found."})
        return _status(row)


@app.get("/api/audits/{audit_id}")
def get_audit(audit_id: str):
    audit_id = _validated_id(audit_id)
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Audit not found."})
        if row.status != "completed":
            return _status(row)
        issues = db.scalars(select(AuditIssue).where(AuditIssue.audit_id == audit_id)).all()
        roasts = db.scalars(select(AuditRoast).where(AuditRoast.audit_id == audit_id)).all()
        score_details = row.scoring_json or {}
        return {
            "overview": {"audit_id": row.id, "website_url": row.website_url, "final_url": row.final_url, "website_title": row.website_title, "overall_score": row.overall_score, "health_label": row.health_label, "status": row.status},
            "category_scores": score_details.get("categories", {}),
            "issues": [{"id": i.issue_id, "category": i.category, "severity": i.severity, "title": i.title, "description": i.description, "evidence": i.evidence_json, "impact": i.impact, "recommendation": i.recommendation, "source": i.source, "confidence": i.confidence} for i in issues],
            "strengths": row.strengths_json or [], "metrics": {key: value for key, value in (row.metrics_json or {}).items() if key != "_category_status"}, "excluded_categories": score_details.get("excluded_categories", []), "low_confidence": row.low_confidence,
            "roasts": {r.intensity: {"status": r.status, "output": (r.payload_json or {}).get("output"), "visual_observations": (r.payload_json or {}).get("visual_observations", []), "error_code": r.error_code, "reason": _roast_reason(r.error_code), "vision_used": r.vision_used, "model": r.model} for r in roasts},
        }


@app.post("/api/audits/{audit_id}/roast")
def roast_audit(audit_id: str, body: RoastRequest):
    audit_id = _validated_id(audit_id)
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Audit not found."})
        if row.status != "completed":
            raise HTTPException(status_code=409, detail={"code": "audit_not_completed", "message": "Roasts are available after the audit completes."})
        roast = db.scalar(select(AuditRoast).where(AuditRoast.audit_id == audit_id, AuditRoast.intensity == body.intensity))
        if roast and not body.regenerate:
            stored = roast.payload_json or {}
            return {"intensity": roast.intensity, "status": roast.status, "output": stored.get("output"), "visual_observations": stored.get("visual_observations", []), "error_code": roast.error_code, "reason": _roast_reason(roast.error_code), "vision_used": roast.vision_used}
        if roast and roast.regenerate_count >= 3:
            raise HTTPException(status_code=429, detail={"code": "regeneration_limit", "message": "The regeneration limit has been reached."})
        status, payload, code, vision = generate_roast(row, body.intensity)
        if roast:
            roast.status, roast.payload_json, roast.model, roast.vision_used, roast.error_code = status, payload, os.getenv("GEMINI_MODEL"), vision, code
            roast.regenerate_count += 1
        else:
            roast = AuditRoast(audit_id=audit_id, intensity=body.intensity, status=status, payload_json=payload,
                               model=os.getenv("GEMINI_MODEL"), vision_used=vision, error_code=code)
            db.add(roast)
        db.commit()
        stored = payload or {}
        return {"intensity": roast.intensity, "status": status, "output": stored.get("output"), "visual_observations": stored.get("visual_observations", []), "error_code": code, "reason": _roast_reason(code), "vision_used": vision}


@app.get("/api/audits/{audit_id}/screenshots/{viewport}")
def get_screenshot(audit_id: str, viewport: str):
    audit_id = _validated_id(audit_id)
    if viewport not in {"desktop", "tablet", "mobile"}:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Screenshot not found."})
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Audit not found."})
    root = STORAGE_ROOT.resolve()
    path = (root / audit_id.replace("-", "") / f"{viewport}.png").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Screenshot not found."})
    return FileResponse(path, media_type="image/png")
