from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError, Page

from app.schemas.audit import CheckResult, Issue


AXE_PATH = Path(__file__).resolve().parents[2] / "assets" / "axe.min.js"


def _severity(impact: str | None) -> str:
    return {"critical": "critical", "serious": "high", "moderate": "medium", "minor": "low"}.get(impact or "", "medium")


async def run_accessibility(page: Page | None) -> CheckResult:
    if page is None or not AXE_PATH.exists():
        return CheckResult(status="unavailable", reason="Playwright page or pinned axe-core asset is unavailable")
    try:
        await page.add_script_tag(path=str(AXE_PATH))
        result: dict[str, Any] = await page.evaluate("async () => await axe.run(document)")
    except (PlaywrightError, OSError):
        return CheckResult(status="unavailable", reason="axe-core could not run on the page")
    issues: list[Issue] = []
    for violation in result.get("violations", [])[:50]:
        evidence: list[str] = []
        for node in violation.get("nodes", [])[:10]:
            target = node.get("target")
            evidence.append(f"rule={violation.get('id')}; target={target}; html={str(node.get('html', ''))[:200]}")
        if not evidence:
            evidence.append(f"rule={violation.get('id')}; nodes=0")
        issues.append(Issue(id=f"accessibility-axe-{violation.get('id')}", category="accessibility", severity=_severity(violation.get("impact")), title=str(violation.get("help", violation.get("id"))), description=str(violation.get("description", "axe-core violation")), evidence=evidence, impact="Users with disabilities may be unable to perceive or operate this content.", recommendation=str(violation.get("helpUrl", "Fix the reported axe-core violation.")), source="axe", confidence="measured"))
    return CheckResult(status="ok", issues=issues, metrics={"violations": len(result.get("violations", [])), "note": "Automated testing catches only part of accessibility problems; manual testing is still required."})
