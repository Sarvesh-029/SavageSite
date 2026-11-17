from __future__ import annotations

from urllib.parse import urljoin

import httpx

from app.schemas.audit import CheckResult, Issue
from app.schemas.scan import ScanResult


def _issue(issue_id: str, severity: str, title: str, description: str, evidence: list[str], impact: str, recommendation: str) -> Issue:
    return Issue(id=issue_id, category="seo", severity=severity, title=title, description=description, evidence=evidence, impact=impact, recommendation=recommendation, source="dom", confidence="measured")


async def run_seo(scan: ScanResult, *, client: httpx.AsyncClient | None = None) -> CheckResult:
    if scan.error or not scan.final_url:
        return CheckResult(status="unavailable", reason="scan did not produce a page")
    issues: list[Issue] = []
    if not scan.title:
        issues.append(_issue("seo-missing-title", "high", "Missing page title", "The document has no non-empty title.", ["document.title is empty"], "Search engines and users cannot identify the page clearly.", "Add a concise, unique title element."))
    elif len(scan.title) < 30:
        issues.append(_issue("seo-title-too-short", "low", "Title is short", "The title is shorter than the recommended range.", [f"document.title length={len(scan.title)}"], "The result may use less descriptive search-result text.", "Write a descriptive title of roughly 30–60 characters."))
    elif len(scan.title) > 60:
        issues.append(_issue("seo-title-too-long", "low", "Title is long", "The title exceeds the recommended range.", [f"document.title length={len(scan.title)}"], "Search engines may truncate the title.", "Shorten the title while preserving its primary topic."))
    if not scan.meta_description:
        issues.append(_issue("seo-missing-meta-description", "medium", "Missing meta description", "No meta description was observed in the document head.", ["meta[name=description] not found or empty"], "Search engines may generate a less relevant snippet.", "Add a unique, useful meta description."))
    if sum(heading.level == 1 for heading in scan.headings) == 0:
        issues.append(_issue("seo-missing-h1", "medium", "Missing H1", "The document has no level-one heading.", ["heading list contains 0 h1 elements"], "The primary topic is less explicit to search engines and assistive technology.", "Add one descriptive H1 for the page topic."))
    if sum(heading.level == 1 for heading in scan.headings) > 1:
        issues.append(_issue("seo-multiple-h1", "medium", "Multiple H1 headings", "More than one level-one heading was observed.", [f"heading list contains {sum(heading.level == 1 for heading in scan.headings)} h1 elements"], "The document hierarchy has competing primary topics.", "Keep one primary H1 and use lower levels for subsections."))
    previous = 0
    for heading in scan.headings:
        if heading.level > previous + 1 and previous:
            issues.append(_issue("seo-heading-order-skip", "low", "Heading levels skip", "Heading levels jump over an intermediate level.", [f"h{previous} followed by h{heading.level}: {heading.text[:80]!r}"], "The content hierarchy is harder to navigate.", "Use heading levels in sequential structural order."))
            break
        previous = heading.level
    if scan.missing_alt_count:
        issues.append(_issue("seo-images-missing-alt", "medium", "Images missing alt text", "One or more images have no alt attribute.", [f"images missing alt={scan.missing_alt_count}", f"total images={scan.image_count}"], "Important image meaning may be unavailable to search engines and screen readers.", "Add accurate alt text, or use alt=\"\" for decorative images."))
    if not scan.canonical:
        issues.append(_issue("seo-missing-canonical", "low", "Missing canonical URL", "No canonical link was observed.", ["link[rel=canonical] not found"], "Duplicate URL variants may be harder to consolidate.", "Add a canonical link for the preferred URL."))
    metrics = {"title_length": len(scan.title or ""), "h1_count": sum(heading.level == 1 for heading in scan.headings), "image_count": scan.image_count, "missing_alt_count": scan.missing_alt_count}
    own_client = client is None
    try:
        if own_client:
            client = httpx.AsyncClient(timeout=10, follow_redirects=True)
        base = scan.final_url.rstrip("/")
        robots = await client.get(urljoin(base + "/", "/robots.txt"))
        sitemap = await client.get(urljoin(base + "/", "/sitemap.xml"))
        metrics.update({"robots_txt_status": robots.status_code, "sitemap_status": sitemap.status_code})
        if robots.status_code >= 400:
            issues.append(_issue("seo-missing-robots-txt", "low", "Missing robots.txt", "robots.txt was not available at the site root.", [f"GET /robots.txt status={robots.status_code}"], "Crawler directives are not explicitly published.", "Publish a valid robots.txt file."))
        if sitemap.status_code >= 400:
            issues.append(_issue("seo-missing-sitemap", "low", "Missing sitemap.xml", "sitemap.xml was not available at the site root.", [f"GET /sitemap.xml status={sitemap.status_code}"], "Search engines have less explicit URL discovery support.", "Publish and reference an XML sitemap."))
    except (httpx.HTTPError, ValueError) as exc:
        return CheckResult(status="unavailable", reason="robots.txt and sitemap.xml could not be checked", issues=issues, metrics=metrics)
    finally:
        if own_client and client is not None:
            await client.aclose()
    return CheckResult(status="ok", issues=issues, metrics=metrics)
