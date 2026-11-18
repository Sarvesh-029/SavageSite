from __future__ import annotations

from pathlib import Path
from collections.abc import Awaitable, Callable
import logging

from app.schemas.audit import AuditFindings, CheckResult
from app.services.accessibility_service import run_accessibility
from app.services.performance_service import run_performance
from app.services.responsiveness_service import run_responsiveness
from app.services.scanner import open_page, scan
from app.services.seo_service import run_seo
from app.services.strengths import collect_strengths
from app.services.ux_analysis_service import run_ux
from app.utils.url_validator import URLValidationError

logger = logging.getLogger(__name__)


def _unavailable(reason: str) -> CheckResult:
    return CheckResult(status="unavailable", reason=reason)


async def audit(url: str, *, audit_id: str | None = None, progress_callback: Callable[[str], Awaitable[None]] | None = None) -> AuditFindings:
    scan_result = await scan(url, audit_id=audit_id, progress_callback=progress_callback)
    if progress_callback:
        await progress_callback("analyzing_performance")
    try:
        performance_result = await run_performance(scan_result)
    except Exception:
        logger.exception("Performance check failed unexpectedly")
        performance_result = _unavailable("performance check failed")
    if progress_callback:
        await progress_callback("checking_accessibility")
    accessibility_result = _unavailable("scan did not produce a page")
    responsiveness_result = _unavailable("scan did not produce a page")
    ux_result = _unavailable("scan did not produce a page")
    if scan_result.error is None and scan_result.final_url:
        try:
            async with open_page(scan_result.final_url) as page:
                screenshot_dir = Path(next(iter(scan_result.screenshots.values()))).parent if scan_result.screenshots else None
                try:
                    accessibility_result = await run_accessibility(page)
                except Exception:
                    logger.exception("Accessibility check failed unexpectedly")
                    accessibility_result = _unavailable("accessibility check failed")
                if progress_callback:
                    await progress_callback("evaluating_seo")
                try:
                    seo_result = await run_seo(scan_result)
                except Exception:
                    logger.exception("SEO check failed unexpectedly")
                    seo_result = _unavailable("SEO check failed")
                if progress_callback:
                    await progress_callback("inspecting_responsiveness")
                try:
                    responsiveness_result = await run_responsiveness(page, screenshot_dir=screenshot_dir)
                except Exception:
                    logger.exception("Responsiveness check failed unexpectedly")
                    responsiveness_result = _unavailable("responsiveness check failed")
                try:
                    ux_result = await run_ux(page)
                except Exception:
                    logger.exception("UI/UX check failed unexpectedly")
                    ux_result = _unavailable("UI/UX check failed")
        except Exception:
            logger.exception("Browser checks could not open the guarded audit page")
            reason = "guarded audit page could not be opened"
            accessibility_result = _unavailable(reason)
            responsiveness_result = _unavailable(reason)
            ux_result = _unavailable(reason)
    else:
        try:
            seo_result = await run_seo(scan_result)
        except Exception:
            logger.exception("SEO check failed unexpectedly")
            seo_result = _unavailable("SEO check failed")
    if progress_callback and scan_result.error:
        # Non-browser categories still report their checks as they are attempted.
        await progress_callback("evaluating_seo")
        seo_result = await run_seo(scan_result)
        await progress_callback("inspecting_responsiveness")
    category_status = {"seo": seo_result, "accessibility": accessibility_result, "responsiveness": responsiveness_result, "performance": performance_result, "ui_ux": ux_result}
    issues = [issue for result in category_status.values() for issue in result.issues]
    metrics = {category: result.metrics for category, result in category_status.items()}
    return AuditFindings(scan=scan_result, issues=issues, strengths=collect_strengths(scan_result), metrics=metrics, category_status=category_status)
