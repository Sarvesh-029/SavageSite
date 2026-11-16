from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Heading(BaseModel):
    level: int = Field(ge=1, le=6)
    text: str


class ScanError(BaseModel):
    code: Literal["invalid_url", "blocked_target", "timeout", "unreachable", "too_large", "browser_error"]
    message: str


class ScanResult(BaseModel):
    audit_id: str
    requested_url: str
    final_url: str | None = None
    status_code: int | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    robots_meta: str | None = None
    html_lang: str | None = None
    viewport_meta: str | None = None
    headings: list[Heading] = Field(default_factory=list)
    image_count: int = 0
    missing_alt_count: int = 0
    internal_link_count: int = 0
    external_link_count: int = 0
    favicon_url: str | None = None
    screenshots: dict[str, str] = Field(default_factory=dict)
    page_bytes: int = 0
    error: ScanError | None = None


class ValidatedURL(BaseModel):
    url: HttpUrl
    hostname: str
    resolved_ips: list[str]
