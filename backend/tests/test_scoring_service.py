from app.schemas.audit import AuditFindings, CheckResult, Issue
from app.services.scoring_service import score_findings


def issue(i, severity="low", category="seo"):
    return Issue(id=i, category=category, severity=severity, title=i, description="observed", evidence=["fact"], impact="impact", recommendation="fix", source="dom", confidence="measured")


def findings(status=None, issues=None):
    statuses = {c: CheckResult(status="ok", metrics={"performance_score": 100} if c == "performance" else {}) for c in ("performance", "ui_ux", "responsiveness", "seo", "accessibility")}
    if status:
        statuses.update(status)
    return AuditFindings(scan={}, issues=issues or [], category_status=statuses)


def test_perfect_page_is_100():
    result = score_findings(findings())
    assert result.overall_score == 100 and result.health_label == "Healthy"


def test_each_severity_penalty():
    for severity, points in (("critical", 20), ("high", 10), ("medium", 5), ("low", 2)):
        result = score_findings(findings(issues=[issue(severity, severity)]))
        assert result.categories["seo"].score == 100 - points
        assert result.categories["seo"].penalties[0].points == points


def test_floor_at_zero_and_duplicate_ids_once():
    result = score_findings(findings(issues=[issue("same", "critical")] * 6))
    assert result.categories["seo"].score == 80
    assert len(result.categories["seo"].penalties) == 1
    result = score_findings(findings(issues=[issue(str(i), "critical") for i in range(6)]))
    assert result.categories["seo"].score == 0


def test_unavailable_category_rescales_weights_with_math():
    result = score_findings(findings({"performance": CheckResult(status="unavailable", reason="no key")}))
    assert result.categories["ui_ux"].effective_weight == 25 / 75
    assert result.categories["seo"].effective_weight == 15 / 75
    assert sum(c.effective_weight for c in result.categories.values()) == 1


def test_all_unavailable_is_null():
    statuses = {c: CheckResult(status="unavailable", reason="failed") for c in ("performance", "ui_ux", "responsiveness", "seo", "accessibility")}
    result = score_findings(findings(statuses))
    assert result.overall_score is None and result.health_label is None


def test_low_confidence_and_determinism():
    statuses = {c: CheckResult(status="unavailable", reason="failed") for c in ("performance", "ui_ux", "responsiveness")}
    one = score_findings(findings(statuses))
    assert one.low_confidence
    data = findings(issues=[issue("x", "medium")])
    assert score_findings(data).model_dump() == score_findings(data).model_dump()
