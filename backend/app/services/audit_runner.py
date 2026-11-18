from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import Audit, AuditIssue, CategoryScoreRow
from app.services.audit_engine import audit
from app.services.scoring_service import score_findings
from app.utils.url_validator import URLValidationError

logger = logging.getLogger(__name__)
STAGES = ["initializing", "loading_website", "inspecting_structure", "analyzing_performance", "checking_accessibility", "evaluating_seo", "inspecting_responsiveness", "preparing_report", "completed"]
MAX_CONCURRENT_AUDITS = max(1, int(os.getenv("MAX_CONCURRENT_AUDITS", "2")))
AUDIT_TIMEOUT_SECONDS = max(1, int(os.getenv("AUDIT_TIMEOUT_SECONDS", "120")))
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AUDITS)


def _now():
    return datetime.now(timezone.utc)


def _write_stage(audit_id: str, stage: str) -> None:
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if row:
            row.stage = stage
            row.stage_index = STAGES.index(stage) + 1
            if stage == "loading_website":
                row.status = "running"
                row.started_at = _now()
            db.commit()


def _load_url(audit_id: str) -> str | None:
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        return row.website_url if row else None


def _store_findings(audit_id: str, findings, scoring) -> None:
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if row is None:
            return
        row.final_url = findings.scan.final_url
        row.website_title = findings.scan.title
        row.scan_json = findings.scan.model_dump(mode="json")
        row.metrics_json = {**findings.metrics, "_category_status": {category: result.model_dump(mode="json") for category, result in findings.category_status.items()}}
        row.strengths_json = [item.model_dump(mode="json") for item in findings.strengths]
        row.scoring_json = scoring.model_dump(mode="json")
        row.overall_score = scoring.overall_score
        row.health_label = scoring.health_label
        row.low_confidence = scoring.low_confidence
        row.issues.clear()
        row.category_scores.clear()
        for issue in findings.issues:
            row.issues.append(AuditIssue(issue_id=issue.id, category=issue.category, severity=issue.severity, title=issue.title, description=issue.description, evidence_json=issue.evidence, impact=issue.impact, recommendation=issue.recommendation, source=issue.source, confidence=issue.confidence))
        for category, item in scoring.categories.items():
            row.category_scores.append(CategoryScoreRow(category=category, score=item.score, status=item.status, original_weight=item.original_weight, effective_weight=item.effective_weight))
        row.status = "completed"
        row.stage = "completed"
        row.stage_index = len(STAGES)
        row.completed_at = _now()
        db.commit()


def recover_orphans() -> None:
    with SessionLocal() as db:
        rows = db.query(Audit).filter(Audit.status.in_(["queued", "running"])).all()
        for row in rows:
            row.status = "failed"
            row.stage = "failed"
            row.error_code = "server_restarted"
            row.error_message = "The server restarted before this audit finished. Please submit it again."
            row.completed_at = _now()
        db.commit()


async def run_audit(audit_id: str) -> None:
    async with _semaphore:
        _write_stage(audit_id, "initializing")
        try:
            async with asyncio.timeout(AUDIT_TIMEOUT_SECONDS):
                url = await asyncio.to_thread(_load_url, audit_id)
                if url is None:
                    return

                async def progress(stage: str) -> None:
                    await asyncio.to_thread(_write_stage, audit_id, stage)

                findings = await audit(url, audit_id=audit_id.replace("-", ""), progress_callback=progress)
                if findings.scan.error:
                    error = findings.scan.error
                    code = error.code if error.code in {"blocked_target", "unreachable", "too_large", "timeout"} else "internal_error"
                    messages = {"blocked_target": "The target is blocked by security rules.", "unreachable": "The target could not be reached.", "too_large": "The target exceeds the scan size limit.", "timeout": "The audit exceeded its time limit.", "internal_error": "The audit could not be completed due to an internal error."}
                    logger.error("Scanner failed for audit %s with code %s: %s", audit_id, code, error.message)
                    await asyncio.to_thread(_fail, audit_id, code, messages[code])
                    return
                scoring = score_findings(findings)
                await asyncio.to_thread(_write_stage, audit_id, "preparing_report")
                await asyncio.to_thread(_store_findings, audit_id, findings, scoring)
        except TimeoutError:
            await asyncio.to_thread(_fail, audit_id, "timeout", "The audit exceeded its time limit.")
        except Exception as exc:
            logger.exception("Unexpected audit failure for %s", audit_id, exc_info=exc)
            await asyncio.to_thread(_fail, audit_id, "internal_error", "The audit could not be completed due to an internal error.")


def _fail(audit_id: str, code: str, message: str) -> None:
    with SessionLocal() as db:
        row = db.get(Audit, audit_id)
        if row:
            row.status, row.stage, row.error_code, row.error_message, row.completed_at = "failed", "failed", code, message, _now()
            db.commit()
