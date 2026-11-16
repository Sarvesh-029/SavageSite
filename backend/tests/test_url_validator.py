from __future__ import annotations

import socket

import pytest

from app.utils.url_validator import URLValidationError, validate_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://127.0.0.1",
        "http://0.0.0.0",
        "http://[::1]",
        "http://169.254.169.254",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://100.64.0.1",
        "file:///etc/passwd",
        "ftp://x.com",
        "http://user:pass@example.com",
        "http://example.com:8080",
        "http://2130706433",
        "http://0x7f000001",
    ],
)
async def test_validator_rejects_unsafe_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)
    with pytest.raises(URLValidationError):
        await validate_url(url)


@pytest.mark.asyncio
async def test_validator_rejects_private_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)

    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(URLValidationError, match="blocked"):
        await validate_url("https://example.test")


@pytest.mark.asyncio
async def test_validator_accepts_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)
    result = await validate_url("https://example.com")
    assert result.hostname == "example.com"
    assert result.resolved_ips


@pytest.mark.asyncio
async def test_private_fixture_allowed_only_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")
    result = await validate_url("http://127.0.0.1:8765")
    assert result.resolved_ips == ["127.0.0.1"]
