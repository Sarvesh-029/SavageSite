from __future__ import annotations

from pathlib import Path

from playwright.async_api import Error as PlaywrightError, Page

from app.schemas.audit import CheckResult, Issue


VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (375, 812)}


def _issue(issue_id: str, severity: str, title: str, description: str, evidence: list[str], impact: str, recommendation: str) -> Issue:
    return Issue(id=issue_id, category="responsiveness", severity=severity, title=title, description=description, evidence=evidence, impact=impact, recommendation=recommendation, source="dom", confidence="measured")


async def run_responsiveness(page: Page | None, *, screenshot_dir: Path | None = None) -> CheckResult:
    if page is None:
        return CheckResult(status="unavailable", reason="Playwright page is unavailable")
    issues: list[Issue] = []
    metrics: dict[str, object] = {}
    try:
        for name, (width, height) in VIEWPORTS.items():
            await page.set_viewport_size({"width": width, "height": height})
            if screenshot_dir:
                await page.screenshot(path=str(screenshot_dir / f"{name}.png"), full_page=True, animations="disabled")
            data = await page.evaluate("""() => {
              const viewport = document.documentElement.clientWidth;
              const elements = [...document.querySelectorAll('*')];
              const wide = elements.filter(el => el.getBoundingClientRect().width > viewport + 1).slice(0, 8).map(el => `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}: ${Math.round(el.getBoundingClientRect().width)}px`);
              const smallText = [...document.querySelectorAll('body *')].filter(el => getComputedStyle(el).fontSize && parseFloat(getComputedStyle(el).fontSize) < 12 && (el.textContent || '').trim()).slice(0, 8).map(el => `${el.tagName.toLowerCase()}: ${getComputedStyle(el).fontSize}`);
              const smallTargets = [...document.querySelectorAll('a,button,input,select,textarea,[role="button"]')].filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && (r.width < 44 || r.height < 44); }).slice(0, 8).map(el => `${el.tagName.toLowerCase()}: ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`);
              const overflowImages = [...document.images].filter(img => img.getBoundingClientRect().right > viewport + 1).slice(0, 8).map(img => `${img.currentSrc || img.src}: ${Math.round(img.getBoundingClientRect().width)}px`);
              return {viewport, scrollWidth: document.documentElement.scrollWidth, wide, smallText, smallTargets, overflowImages, hasViewport: !!document.querySelector('meta[name="viewport"]')};
            }""")
            metrics[name] = data
            if data["scrollWidth"] > data["viewport"]:
                issues.append(_issue("responsiveness-horizontal-overflow", "high", "Horizontal overflow", "The document is wider than the viewport.", [f"viewport={data['viewport']}px; scrollWidth={data['scrollWidth']}px; viewport={name}"], "Mobile users must scroll sideways to reach content.", "Constrain layout widths and handle overflowing content."))
            if data["wide"]:
                issues.append(_issue("responsiveness-wide-element", "high", "Element wider than viewport", "One or more elements exceed the viewport width.", [f"viewport={name}; {item}" for item in data["wide"]], "A fixed-width element can break responsive layout.", "Use fluid sizing and max-width: 100%."))
            if not data["hasViewport"]:
                issues.append(_issue("responsiveness-missing-viewport", "high", "Missing viewport meta", "No responsive viewport declaration was observed.", ["meta[name=viewport] not found"], "Mobile browsers may render the page at a desktop layout width.", "Add a width=device-width viewport declaration."))
            if name == "mobile" and data["smallText"]:
                issues.append(_issue("responsiveness-tiny-mobile-text", "medium", "Text is too small on mobile", "Visible text below 12px was observed on the mobile viewport.", [f"viewport=mobile; {item}" for item in data["smallText"]], "Small text is difficult to read on touch devices.", "Use a readable mobile font size."))
            if name == "mobile" and data["smallTargets"]:
                issues.append(_issue("responsiveness-small-tap-targets", "medium", "Small tap targets", "Interactive elements smaller than 44px were observed.", [f"viewport=mobile; {item}" for item in data["smallTargets"]], "Small controls are difficult to activate accurately.", "Provide at least 44px by 44px target areas."))
            if data["overflowImages"]:
                issues.append(_issue("responsiveness-overflowing-images", "medium", "Images overflow their container", "One or more images extend beyond the viewport.", [f"viewport={name}; {item}" for item in data["overflowImages"]], "Images can cause clipping and horizontal scrolling.", "Use responsive image sizing and containment."))
    except (PlaywrightError, OSError):
        return CheckResult(status="unavailable", reason="responsive DOM measurements could not be collected", issues=issues, metrics=metrics)
    return CheckResult(status="ok", issues=issues, metrics=metrics)
