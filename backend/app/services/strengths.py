from __future__ import annotations

from app.schemas.audit import Strength
from app.schemas.scan import ScanResult


def collect_strengths(scan: ScanResult) -> list[Strength]:
    if scan.error:
        return []
    strengths: list[Strength] = []
    if scan.viewport_meta:
        strengths.append(Strength(id="strength-valid-viewport-meta", category="responsiveness", title="Responsive viewport is declared", description="The document declares a viewport meta tag.", evidence=[f"meta[name=viewport]={scan.viewport_meta}"]))
    if scan.image_count == 0 or scan.missing_alt_count == 0:
        strengths.append(Strength(id="strength-images-have-alt", category="accessibility", title="Images have alt coverage", description="All observed images include an alt attribute.", evidence=[f"images={scan.image_count}; missing_alt={scan.missing_alt_count}"]))
    if scan.html_lang:
        strengths.append(Strength(id="strength-html-lang", category="accessibility", title="Document language is declared", description="The root HTML element declares a language.", evidence=[f"html lang={scan.html_lang}"]))
    return strengths
