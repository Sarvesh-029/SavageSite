from __future__ import annotations

from app.schemas.audit import AuditFindings, Category, Issue
from app.schemas.scoring import CategoryScore, ExcludedCategory, Penalty, ScoreBreakdown

SCORING_VERSION = "1.0"
WEIGHTS: dict[Category, float] = {
    "performance": 25,
    "ui_ux": 25,
    "responsiveness": 20,
    "seo": 15,
    "accessibility": 15,
}
PENALTY_POINTS = {"critical": 20, "high": 10, "medium": 5, "low": 2}


def score_findings(findings: AuditFindings) -> ScoreBreakdown:
    available: dict[Category, int | float] = {}
    excluded: list[ExcludedCategory] = []
    category_scores: dict[Category, CategoryScore] = {}
    issues_by_category: dict[Category, list[Issue]] = {category: [] for category in WEIGHTS}
    for issue in findings.issues:
        issues_by_category[issue.category].append(issue)

    for category, weight in WEIGHTS.items():
        result = findings.category_status.get(category)
        if result is None or result.status != "ok":
            reason = result.reason if result and result.reason else "check did not produce a result"
            excluded.append(ExcludedCategory(category=category, reason=reason))
            category_scores[category] = CategoryScore(score=None, status="unavailable", original_weight=weight, effective_weight=0, penalties=[])
            continue
        if category == "performance":
            score = result.metrics.get("performance_score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                excluded.append(ExcludedCategory(category=category, reason="performance score was not provided"))
                category_scores[category] = CategoryScore(score=None, status="unavailable", original_weight=weight, effective_weight=0, penalties=[])
                continue
            score = max(0, min(100, score))
            available[category] = score
            category_scores[category] = CategoryScore(score=score, status="ok", original_weight=weight, effective_weight=0, penalties=[])
            continue

        unique: dict[str, Issue] = {}
        for issue in issues_by_category[category]:
            unique.setdefault(issue.id, issue)
        penalties = [Penalty(issue_id=i.id, severity=i.severity, points=PENALTY_POINTS[i.severity]) for i in unique.values()]
        score = max(0, 100 - sum(item.points for item in penalties))
        available[category] = score
        category_scores[category] = CategoryScore(score=score, status="ok", original_weight=weight, effective_weight=0, penalties=penalties)

    total_weight = sum(WEIGHTS[c] for c in available)
    for category in available:
        item = category_scores[category]
        item.effective_weight = WEIGHTS[category] / total_weight if total_weight else 0
    overall = round(sum(float(score) * category_scores[cat].effective_weight for cat, score in available.items())) if available else None
    label = None if overall is None else "Healthy" if overall >= 90 else "Decent" if overall >= 70 else "Needs work" if overall >= 50 else "Critical"
    return ScoreBreakdown(categories=category_scores, overall_score=overall, excluded_categories=excluded, low_confidence=len(available) < 3, health_label=label, scoring_version=SCORING_VERSION)
