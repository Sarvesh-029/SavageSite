from __future__ import annotations

from pathlib import Path

from app.schemas.audit import AuditFindings, CheckResult
from app.services.accessibility_service import run_accessibility
from app.services.performance_service import run_performance
from app.services.responsiveness_service import run_responsiveness
from app.services.scanner import open_page, scan
from app.services.seo_service import run_seo
from app.services.strengths import collect_strengths
from app.services.ux_analysis_service import run_ux
from app.utils.url_validator import URLValidationError


def _unavailable(reason: str) -> CheckResult:
    return CheckResult(status="unavailable", reason=reason)


async def audit(url: str, *, audit_id: str | None = None) -> AuditFindings:
    scan_result = await scan(url, audit_id=audit_id)
    seo_result, performance_result = await __import__("asyncio").gather(run_seo(scan_result), run_performance(scan_result))
    accessibility_result = _unavailable("scan did not produce a page")
    responsiveness_result = _unavailable("scan did not produce a page")
    ux_result = _unavailable("scan did not produce a page")
    if scan_result.error is None and scan_result.final_url:
        try:
            async with open_page(scan_result.final_url) as page:
                screenshot_dir = Path(next(iter(scan_result.screenshots.values()))).parent if scan_result.screenshots else None
                accessibility_result = await run_accessibility(page)
                responsiveness_result = await run_responsiveness(page, screenshot_dir=screenshot_dir)
                ux_result = await run_ux(page)
        except (URLValidationError, OSError):
            reason = "guarded audit page could not be opened"
            accessibility_result = _unavailable(reason)
            responsiveness_result = _unavailable(reason)
            ux_result = _unavailable(reason)
    category_status = {"seo": seo_result, "accessibility": accessibility_result, "responsiveness": responsiveness_result, "performance": performance_result, "ui_ux": ux_result}
    issues = [issue for result in category_status.values() for issue in result.issues]
    metrics = {category: result.metrics for category, result in category_status.items()}
    return AuditFindings(scan=scan_result, issues=issues, strengths=collect_strengths(scan_result), metrics=metrics, category_status=category_status)
