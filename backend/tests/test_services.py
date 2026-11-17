from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.schemas.scan import Heading, ScanResult
from app.services.accessibility_service import run_accessibility
from app.services.responsiveness_service import run_responsiveness
from app.services.seo_service import run_seo
from app.services.ux_analysis_service import run_ux


class NotFoundClient:
    async def get(self, *_args, **_kwargs):
        class Response:
            status_code = 404

        return Response()


@pytest.mark.asyncio
async def test_seo_check_inline_scan() -> None:
    result = await run_seo(ScanResult(audit_id="seo", requested_url="https://example.com", final_url="https://example.com", headings=[Heading(level=1, text="A"), Heading(level=3, text="B")], image_count=1, missing_alt_count=1), client=NotFoundClient())
    ids = {issue.id for issue in result.issues}
    assert {"seo-missing-title", "seo-missing-meta-description", "seo-heading-order-skip", "seo-images-missing-alt", "seo-missing-canonical"}.issubset(ids)


@pytest.mark.asyncio
async def test_browser_checks_inline_html() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 375, "height": 812})
        await page.set_content("""
          <style>body{font-size:11px}.wide{width:1600px}.a{font-family:Arial}.b{font-family:Georgia}.c{font-family:Verdana}.d{font-family:monospace}</style>
          <div class='wide'><p class='a'>One</p><p class='b'>Two</p><p class='c'>Three</p><p class='d'>Four</p><input><img src='x'></div>
        """)
        accessibility = await run_accessibility(page)
        responsiveness = await run_responsiveness(page)
        ux = await run_ux(page)
        await browser.close()
    assert accessibility.status == "ok"
    assert any(issue.id == "accessibility-axe-label" for issue in accessibility.issues)
    assert any(issue.id == "responsiveness-horizontal-overflow" for issue in responsiveness.issues)
    assert any(issue.id == "responsiveness-tiny-mobile-text" for issue in responsiveness.issues)
    assert any(issue.id == "ux-excessive-font-families" for issue in ux.issues)
