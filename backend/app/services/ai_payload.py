from __future__ import annotations

import html
import json
import re
import unicodedata
from urllib.parse import urlsplit

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def clean(value: object, limit: int) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\t\n\r")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def build_payload(audit) -> dict:
    scores = (audit.scoring_json or {}).get("categories", {})
    metrics = {k: v for k, v in (audit.metrics_json or {}).items() if k != "_category_status"}
    issues = sorted(audit.issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.issue_id))
    selected = issues[:25]
    host = urlsplit(audit.final_url or audit.website_url).hostname or ""
    return {
        "hostname": clean(host, 253), "title": clean(audit.website_title, 200),
        "health_label": audit.health_label,
        "category_scores": scores,
        "key_metrics": metrics,
        "issues": [{"id": i.issue_id, "category": i.category, "severity": i.severity,
                    "title": clean(i.title, 200), "evidence": [clean(e, 300) for e in (i.evidence_json or [])],
                    "recommendation": clean(i.recommendation, 500)} for i in selected],
        "issues_omitted": max(0, len(issues) - len(selected)),
        "strengths": [{"id": s.get("id"), "category": s.get("category"), "title": clean(s.get("title"), 200),
                       "description": clean(s.get("description"), 400), "evidence": [clean(e, 300) for e in s.get("evidence", [])]} for s in (audit.strengths_json or [])],
        "excluded_categories": (audit.scoring_json or {}).get("excluded_categories", []),
    }


def user_data_block(payload: dict) -> str:
    return "BEGIN_UNTRUSTED_WEBSITE_DATA_JSON\n" + json.dumps(payload, ensure_ascii=False) + "\nEND_UNTRUSTED_WEBSITE_DATA_JSON"
