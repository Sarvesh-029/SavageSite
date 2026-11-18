from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Error as PlaywrightError, Page, Route, async_playwright

from app.schemas.scan import Heading, ScanError, ScanResult
from app.utils.security import is_unsafe_ip
from app.utils.url_validator import URLValidationError, validate_url


SCAN_TIMEOUT_MS = 30_000
TOTAL_SCAN_BUDGET_SECONDS = 60
MAX_PAGE_BYTES = 10 * 1024 * 1024
MAX_SCREENSHOT_HEIGHT = 6000
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage"


def _error_result(audit_id: str, requested_url: str, error: ScanError) -> ScanResult:
    return ScanResult(audit_id=audit_id, requested_url=requested_url, error=error)


async def _guard_request(route: Route, allowed_private_origin: str | None = None) -> None:
    request = route.request
    try:
        if request.url.startswith(("data:", "blob:")):
            await route.continue_()
            return
        validated = await validate_url(request.url)
        request_origin = f"{urlparse(request.url).scheme}://{urlparse(request.url).netloc}"
        if allowed_private_origin != request_origin and any(is_unsafe_ip(ip) for ip in validated.resolved_ips):
            await route.abort("blockedbyclient")
            return
        if request.resource_type == "download":
            await route.abort("blockedbyclient")
            return
        await route.continue_()
    except URLValidationError:
        await route.abort("blockedbyclient")


async def _extract(page: Page, response_status: int | None) -> dict:
    return await page.evaluate(
        """() => {
          const text = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
          const absolute = (value) => value ? new URL(value, document.baseURI).href : null;
          const links = [...document.querySelectorAll('a[href]')].map(a => absolute(a.getAttribute('href'))).filter(Boolean);
          const host = location.host;
          return {
            final_url: location.href,
            status_code: %s,
            title: document.title || null,
            meta_description: document.querySelector('meta[name="description"]')?.getAttribute('content') || null,
            canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') || null,
            robots_meta: document.querySelector('meta[name="robots"]')?.getAttribute('content') || null,
            html_lang: document.documentElement.getAttribute('lang'),
            viewport_meta: document.querySelector('meta[name="viewport"]')?.getAttribute('content') || null,
            headings: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => ({level: Number(h.tagName.substring(1)), text: text(h)})),
            image_count: document.images.length,
            missing_alt_count: [...document.images].filter(img => !img.hasAttribute('alt')).length,
            internal_link_count: links.filter(link => new URL(link).host === host).length,
            external_link_count: links.filter(link => new URL(link).host !== host).length,
            favicon_url: absolute(document.querySelector('link[rel~="icon"]')?.getAttribute('href')),
          };
        }""" % ("null" if response_status is None else str(response_status))
    )


async def _capture(page: Page, context: BrowserContext, output: Path, width: int, height: int, name: str) -> str:
    await page.set_viewport_size({"width": width, "height": height})
    await page.screenshot(path=str(output / f"{name}.png"), full_page=True, animations="disabled")
    return str(output / f"{name}.png")


@asynccontextmanager
async def open_page(url: str):
    """Open a guarded page for audit checks and close its browser afterwards."""
    await validate_url(url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=False, service_workers="block")
        initial = urlparse(url)
        allowed_private_origin = None
        if os.getenv("ALLOW_PRIVATE_TARGETS", "false").lower() == "true":
            allowed_private_origin = f"{initial.scheme}://{initial.netloc}"
        await context.route("**/*", lambda route: _guard_request(route, allowed_private_origin))
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=SCAN_TIMEOUT_MS)
            final_validated = await validate_url(page.url)
            final_origin = f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}"
            if allowed_private_origin != final_origin and any(is_unsafe_ip(ip) for ip in final_validated.resolved_ips):
                raise URLValidationError("blocked_target", "redirected target was blocked by security rules")
            yield page
        finally:
            await browser.close()


async def scan(url: str, *, audit_id: str | None = None, progress_callback: Callable[[str], Awaitable[None]] | None = None) -> ScanResult:
    audit_id = audit_id or uuid.uuid4().hex
    try:
        await validate_url(url)
    except URLValidationError as exc:
        code = "blocked_target" if exc.code == "blocked_target" else "invalid_url"
        return _error_result(audit_id, url, ScanError(code=code, message=exc.safe_message))

    output = STORAGE_ROOT / audit_id
    output.mkdir(parents=True, exist_ok=True)
    page_bytes = 0
    response_status: int | None = None
    async with async_playwright() as playwright:
        browser: Browser | None = None
        try:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=False, service_workers="block")
            initial = urlparse(url)
            allowed_private_origin = None
            if os.getenv("ALLOW_PRIVATE_TARGETS", "false").lower() == "true":
                allowed_private_origin = f"{initial.scheme}://{initial.netloc}"
            await context.route("**/*", lambda route: _guard_request(route, allowed_private_origin))
            page = await context.new_page()

            response_tasks: set[asyncio.Task] = set()

            async def track_response(response) -> None:
                nonlocal page_bytes
                try:
                    page_bytes += len(await response.body())
                except PlaywrightError:
                    # Some responses (for example aborted streams) have no body.
                    return

            def schedule_response_tracking(response) -> None:
                task = asyncio.create_task(track_response(response))
                response_tasks.add(task)
                task.add_done_callback(response_tasks.discard)

            page.on("response", schedule_response_tracking)
            async with asyncio.timeout(TOTAL_SCAN_BUDGET_SECONDS):
                if progress_callback:
                    await progress_callback("loading_website")
                response = await page.goto(url, wait_until="domcontentloaded", timeout=SCAN_TIMEOUT_MS)
                response_status = response.status if response else None
                final_validated = await validate_url(page.url)
                final_origin = f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}"
                if allowed_private_origin != final_origin and any(is_unsafe_ip(ip) for ip in final_validated.resolved_ips):
                    return _error_result(
                        audit_id,
                        url,
                        ScanError(code="blocked_target", message="redirected target was blocked by security rules"),
                    )
                if page_bytes > MAX_PAGE_BYTES:
                    return _error_result(audit_id, url, ScanError(code="too_large", message="page exceeds the size limit"))
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightError:
                    pass
                if response_tasks:
                    await asyncio.gather(*response_tasks, return_exceptions=True)
                if page_bytes > MAX_PAGE_BYTES:
                    return _error_result(audit_id, url, ScanError(code="too_large", message="page exceeds the size limit"))
                if progress_callback:
                    await progress_callback("inspecting_structure")
                data = await _extract(page, response_status)
                screenshots = {
                    "desktop": await _capture(page, context, output, 1440, 900, "desktop"),
                    "mobile": await _capture(page, context, output, 375, 812, "mobile"),
                }
                return ScanResult(
                    audit_id=audit_id,
                    requested_url=url,
                    screenshots=screenshots,
                    page_bytes=page_bytes,
                    **data,
                )
        except asyncio.TimeoutError:
            return _error_result(audit_id, url, ScanError(code="timeout", message="scan timed out"))
        except URLValidationError:
            return _error_result(audit_id, url, ScanError(code="blocked_target", message="a request was blocked by target security rules"))
        except (PlaywrightError, OSError):
            return _error_result(audit_id, url, ScanError(code="unreachable", message="target could not be scanned"))
        finally:
            if browser is not None:
                await browser.close()
