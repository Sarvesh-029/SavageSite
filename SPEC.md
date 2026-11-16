# SavageSite: Phases 0–2 Specification

## 1. Decisions

- **Performance:** PageSpeed Insights API (key in `PAGESPEED_API_KEY`). No local Lighthouse.
- **Accessibility:** axe-core, a pinned local copy of `axe.min.js` committed under `backend/assets/`, injected via Playwright.
- **Jobs (later phase):** FastAPI `BackgroundTasks`, status stored in DB.
- **Screenshots:** saved to `storage/{audit_id}/{viewport}.png`.
- **Environment variables:** `GEMINI_API_KEY`, `GEMINI_MODEL`, `DATABASE_URL`, `FRONTEND_URL`, `PAGESPEED_API_KEY`, and `ALLOW_PRIVATE_TARGETS` (default `false`, dev/test only).

## 2. Issue schema (the single contract for every check)

Every check returns issues conforming to this contract. Issue IDs are stable and deterministic.

```json
{
  "id": "seo-missing-meta-description",
  "category": "performance | ui_ux | responsiveness | seo | accessibility",
  "severity": "critical | high | medium | low",
  "title": "string",
  "description": "string",
  "evidence": ["concrete observed facts, e.g. selector, value, count"],
  "impact": "string",
  "recommendation": "string",
  "source": "lighthouse | axe | dom | vision",
  "confidence": "measured | heuristic"
}
```

The Pydantic implementation lives in `backend/app/schemas/`.

## 3. Scoring rules (implemented in a later phase, defined now)

- Performance score = Lighthouse performance score (0–100).
- SEO, Accessibility, Responsiveness, and UI/UX start at 100 and lose points per issue: critical −20, high −10, medium −5, low −2, floored at 0.
- Weights: Performance 25, UI/UX 25, Responsiveness 20, SEO 15, Accessibility 15.
- If a category is `unavailable`, exclude it and rescale the remaining weights to sum to 1. Report which categories were excluded.
- Scoring is deterministic. AI never changes scores.

## 4. Status stages (for the later job system)

`initializing`, `loading_website`, `inspecting_structure`, `analyzing_performance`, `checking_accessibility`, `evaluating_seo`, `inspecting_responsiveness`, `generating_ai`, `preparing_report`, `completed`, `failed`.

## 5. Security rules

- Only `http` and `https`. Ports 80 and 443 only. No credentials in the URL. Maximum URL length 2048.
- Resolve DNS and check **all** returned A/AAAA records. Block loopback, private, link-local (including `169.254.169.254`), CGNAT (`100.64.0.0/10`), multicast, reserved, unspecified, and IPv6 equivalents, including IPv4-mapped IPv6.
- Re-validate on every redirect and every subresource request made by the browser.
- Use timeouts, response-size caps, and disabled downloads. Never expose internal exception text to callers.
- `ALLOW_PRIVATE_TARGETS=true` exists only so tests can scan a local fixture. It defaults to `false`.

## Phase gates

- **Gate 0:** `SPEC.md` exists, the scaffold exists, `pip install -r requirements.txt` and `playwright install chromium` work. Stop.
- **Gate 1:** all scanner tests pass; `scan_cli.py` works on two real public sites and produces screenshots plus metadata. Paste actual output. Stop.
- **Gate 2:** all audit tests pass; `audit_cli.py` works on the fixture and two real sites. Paste the real output summary, unavailable categories and reasons, and any low-confidence checks. Stop.

## Residual DNS-rebinding risk

The scanner will re-resolve and validate the destination for navigation, redirects, and each browser request. DNS can still change between validation and connection at the operating-system, browser, proxy, or network layer; this is a residual DNS-rebinding/TOCTOU risk. The scanner must document this limitation and should run with downloads disabled, strict timeouts, response-size caps, and least privilege.

