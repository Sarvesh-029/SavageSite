from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.schemas.scan import ValidatedURL
from app.services.scanner import scan
from app.services import scanner


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/private")
            self.end_headers()
            return
        body = b"<!doctype html><html lang='en'><head><title>Fixture</title><meta name='viewport' content='width=device-width'></head><body><h1>Hello</h1><img src='x.png'></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


@pytest.fixture
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_local_fixture_scan_is_allowed_only_in_test_mode(monkeypatch: pytest.MonkeyPatch, fixture_server) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")
    result = await scan(f"http://127.0.0.1:{fixture_server.server_port}", audit_id="fixture-test")
    assert result.error is None
    assert result.title == "Fixture"
    assert result.image_count == 1
    assert set(result.screenshots) == {"desktop", "mobile"}


@pytest.mark.asyncio
async def test_redirect_to_different_private_origin_is_blocked(monkeypatch: pytest.MonkeyPatch, fixture_server) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")
    result = await scan(f"http://localhost:{fixture_server.server_port}/redirect", audit_id="redirect-test")
    assert result.error is not None
    assert result.error.code in {"unreachable", "blocked_target"}


@pytest.mark.asyncio
async def test_request_guard_aborts_private_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRequest:
        url = "http://127.0.0.1/private"
        resource_type = "document"

    class FakeRoute:
        request = FakeRequest()

        def __init__(self):
            self.aborted = None

        async def abort(self, error):
            self.aborted = error

        async def continue_(self):
            raise AssertionError("unsafe request was continued")

    async def fake_validate(_url):
        return ValidatedURL(url="http://127.0.0.1/private", hostname="127.0.0.1", resolved_ips=["127.0.0.1"])

    monkeypatch.setattr(scanner, "validate_url", fake_validate)
    route = FakeRoute()
    await scanner._guard_request(route, "http://localhost:8765")
    assert route.aborted == "blockedbyclient"
