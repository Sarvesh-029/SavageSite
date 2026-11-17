from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest

from app.services.audit_engine import audit
from app.services.performance_service import run_performance
from app.schemas.scan import ScanResult


FIXTURE_HTML = Path(__file__).parent / "fixtures" / "broken_site" / "index.html"
EXPECTED = json.loads((FIXTURE_HTML.parent / "EXPECTED.json").read_text(encoding="utf-8"))


class BrokenSiteHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/index.html" or self.path == "/":
            body = FIXTURE_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args) -> None:
        return


@pytest.fixture
def broken_site_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BrokenSiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_fixture_finds_expected_evidence_backed_issues(monkeypatch: pytest.MonkeyPatch, broken_site_server) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")
    result = await audit(f"http://127.0.0.1:{broken_site_server.server_port}", audit_id="broken-site")
    issue_ids = {issue.id for issue in result.issues}
    assert set(EXPECTED).issubset(issue_ids)
    assert result.category_status["performance"].status == "unavailable"
    assert result.category_status["performance"].reason == "PAGESPEED_API_KEY is not configured"
    assert all(issue.evidence and all(item.strip() for item in issue.evidence) for issue in result.issues)


@pytest.mark.asyncio
async def test_performance_is_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
    result = await run_performance(ScanResult(audit_id="x", requested_url="https://example.com", final_url="https://example.com"))
    assert result.status == "unavailable"
    assert result.reason == "PAGESPEED_API_KEY is not configured"
