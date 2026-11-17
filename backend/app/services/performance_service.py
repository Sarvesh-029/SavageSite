from __future__ import annotations

import os
from typing import Any

import httpx

from app.schemas.audit import CheckResult, Issue
from app.schemas.scan import ScanResult


async def run_performance(scan: ScanResult, *, client: httpx.AsyncClient | None = None) -> CheckResult:
    key = os.getenv("PAGESPEED_API_KEY")
    if not key:
        return CheckResult(status="unavailable", reason="PAGESPEED_API_KEY is not configured")
    if scan.error:
        return CheckResult(status="unavailable", reason="scan target is unavailable")
    own_client = client is None
    try:
        if own_client:
            client = httpx.AsyncClient(timeout=30)
        response = await client.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params={"url": scan.final_url, "strategy": "mobile", "key": key})
        if response.status_code == 429:
            return CheckResult(status="unavailable", reason="PageSpeed Insights rate limit reached")
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        lighthouse = payload.get("lighthouseResult", {})
        score = lighthouse.get("categories", {}).get("performance", {}).get("score")
        audits = lighthouse.get("audits", {})
        metrics = {"performance_score": round(score * 100, 1) if isinstance(score, (int, float)) else None}
        for key_name, audit_id in {"fcp": "first-contentful-paint", "lcp": "largest-contentful-paint", "tbt": "total-blocking-time", "cls": "cumulative-layout-shift", "speed_index": "speed-index"}.items():
            metrics[key_name] = audits.get(audit_id, {}).get("displayValue")
        issues: list[Issue] = []
        for audit_id, audit in audits.items():
            score_value = audit.get("score")
            if audit.get("details", {}).get("type") == "opportunity" and isinstance(score_value, (int, float)) and score_value < 0.9:
                issues.append(Issue(id=f"performance-opportunity-{audit_id}", category="performance", severity="medium", title=str(audit.get("title", audit_id)), description=str(audit.get("description", "PageSpeed opportunity")), evidence=[f"displayValue={audit.get('displayValue', 'n/a')}", f"score={score_value}"], impact="The page may load or become interactive more slowly.", recommendation="Apply the PageSpeed Insights opportunity recommendations.", source="lighthouse", confidence="measured"))
        return CheckResult(status="ok", issues=issues[:50], metrics=metrics)
    except (httpx.HTTPError, ValueError, KeyError):
        return CheckResult(status="unavailable", reason="PageSpeed Insights could not analyze the target")
    finally:
        if own_client and client is not None:
            await client.aclose()
