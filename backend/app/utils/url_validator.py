from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from app.schemas.scan import ValidatedURL
from app.utils.security import TargetSecurityError, assert_safe_ip


@dataclass
class URLValidationError(ValueError):
    code: str
    safe_message: str

    def __str__(self) -> str:
        return self.safe_message


def _private_targets_allowed() -> bool:
    return os.getenv("ALLOW_PRIVATE_TARGETS", "false").lower() == "true"


def _looks_like_encoded_ip(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    if normalized.startswith(("0x", "0o")) and re.fullmatch(r"0[xo][0-9a-f]+", normalized):
        return True
    return bool(re.fullmatch(r"[0-9]+", normalized))


async def _resolve(hostname: str, port: int) -> list[str]:
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise URLValidationError("unreachable", "target hostname could not be resolved") from exc
    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise URLValidationError("unreachable", "target hostname could not be resolved")
    return addresses


async def validate_url(url: str) -> ValidatedURL:
    if len(url) > 2048:
        raise URLValidationError("invalid_url", "URL is too long")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise URLValidationError("invalid_url", "URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise URLValidationError("invalid_url", "only http and https URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise URLValidationError("invalid_url", "URL credentials are not allowed")
    if not parsed.hostname:
        raise URLValidationError("invalid_url", "URL hostname is required")
    try:
        port = parsed.port
    except ValueError as exc:
        raise URLValidationError("invalid_url", "URL port is invalid") from exc
    if port is not None and port not in {80, 443}:
        if not (_private_targets_allowed() and port >= 1 and port <= 65535):
            raise URLValidationError("invalid_url", "only ports 80 and 443 are allowed")
    hostname = parsed.hostname.rstrip(".")
    if _looks_like_encoded_ip(hostname):
        raise URLValidationError("blocked_target", "encoded IP literals are not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        try:
            ip = assert_safe_ip(literal, allow_private=_private_targets_allowed())
        except TargetSecurityError as exc:
            raise URLValidationError("blocked_target", "target address is not publicly routable") from exc
        addresses = [ip]
    else:
        addresses = await _resolve(hostname, port or (443 if parsed.scheme.lower() == "https" else 80))
        try:
            addresses = [assert_safe_ip(address, allow_private=_private_targets_allowed()) for address in addresses]
        except TargetSecurityError as exc:
            raise URLValidationError("blocked_target", "target resolves to a blocked address") from exc
    return ValidatedURL(url=url, hostname=hostname, resolved_ips=addresses)
