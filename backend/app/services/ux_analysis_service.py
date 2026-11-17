from __future__ import annotations

from playwright.async_api import Error as PlaywrightError, Page

from app.schemas.audit import CheckResult, Issue


def _ux(issue_id: str, severity: str, title: str, description: str, evidence: list[str], impact: str, recommendation: str) -> Issue:
    # These are DOM-based heuristics, not visual inspection or user research.
    return Issue(id=issue_id, category="ui_ux", severity=severity, title=title, description=description, evidence=evidence, impact=impact, recommendation=recommendation, source="dom", confidence="heuristic")


async def run_ux(page: Page | None) -> CheckResult:
    if page is None:
        return CheckResult(status="unavailable", reason="Playwright page is unavailable")
    try:
        data = await page.evaluate("""() => {
          const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
          const text = [...document.querySelectorAll('body *')].filter(visible).map(el => getComputedStyle(el).fontFamily).filter(Boolean);
          const ctas = [...document.querySelectorAll('a,button,input[type=submit],[role=button]')].filter(visible).filter(el => /start|buy|sign|contact|learn|join|download/i.test(el.textContent || el.value || ''));
          const navItems = [...document.querySelectorAll('nav a, nav button, header a, header button')].filter(visible).length;
          const bodyFont = getComputedStyle(document.body).fontSize;
          const largeBlocks = [...document.querySelectorAll('p,section,article,main')].filter(visible).slice(0, 50).map(el => { const s=getComputedStyle(el); return {color:s.color, background:s.backgroundColor, text:(el.textContent || '').trim().slice(0,80)}; });
          return {fonts:[...new Set(text)], ctaAboveFold: ctas.some(el => el.getBoundingClientRect().top < innerHeight), navItems, bodyFont, largeBlocks};
        }""")
    except PlaywrightError:
        return CheckResult(status="unavailable", reason="UI/UX DOM heuristics could not run")
    issues: list[Issue] = []
    if not data["ctaAboveFold"]:
        issues.append(_ux("ux-no-primary-cta-above-fold", "medium", "No primary CTA above the fold", "No visible action-oriented CTA was found in the initial viewport.", ["matching visible CTA elements above fold=0"], "Users may not know what to do next immediately.", "Place a clear primary action in the initial viewport."))
    if len(data["fonts"]) > 3:
        issues.append(_ux("ux-excessive-font-families", "low", "Many font families", "More than three font families are used in visible DOM elements.", [f"font families={data['fonts']}"], "Visual hierarchy and loading performance may suffer.", "Reduce the number of font families and weights."))
    try:
        if float(str(data["bodyFont"]).replace("px", "")) < 14:
            issues.append(_ux("ux-body-text-too-small", "medium", "Body text is too small", "The computed body font size is below 14px.", [f"body font-size={data['bodyFont']}"], "Small body text reduces readability.", "Use a body text size of at least 14px."))
    except ValueError:
        pass
    if data["navItems"] > 8:
        issues.append(_ux("ux-excessive-nav-items", "low", "Navigation has many items", "The header/navigation contains more than eight visible controls.", [f"visible nav controls={data['navItems']}"], "Dense navigation increases cognitive load.", "Group secondary links or use a clearer information hierarchy."))
    return CheckResult(status="ok", issues=issues, metrics={"font_families": data["fonts"], "nav_items": data["navItems"], "body_font": data["bodyFont"], "note": "UI/UX checks are DOM-based heuristics, not visual inspection."})
