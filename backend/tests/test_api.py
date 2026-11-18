from __future__ import annotations

import pytest
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.schemas.audit import AuditFindings, CheckResult
from app.schemas.scan import ScanResult
from app.services import audit_runner
from app.services.scoring_service import score_findings
from app import main
from app.models import Audit


@pytest.fixture
def client(monkeypatch, tmp_path):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(audit_runner, "SessionLocal", factory)
    monkeypatch.setattr(main, "engine", test_engine)
    from app.services import scanner
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(scanner, "STORAGE_ROOT", storage_root)
    monkeypatch.setattr(main, "STORAGE_ROOT", storage_root)
    with TestClient(main.app) as test_client:
        yield test_client, factory
    test_engine.dispose()


def test_create_status_nonfinished_and_invalid_targets(client, monkeypatch):
    c, factory = client
    monkeypatch.setattr(main, "run_audit", lambda _audit_id: None)
    for url in ("http://localhost", "http://169.254.169.254"):
        assert c.post("/api/audits", json={"url": url}).status_code == 422
    with factory() as db:
        assert db.query(Audit).count() == 0
    response = c.post("/api/audits", json={"url": "https://example.com"})
    assert response.status_code == 202
    audit_id = response.json()["audit_id"]
    assert c.get(f"/api/audits/{audit_id}").json()["status"] == "queued"
    assert c.get("/api/audits/not-a-uuid/status").status_code == 404
    assert c.get(f"/api/audits/{'0' * 8}-0000-0000-0000-000000000000/status").status_code == 404


def test_pipeline_stages_and_failure_of_one_check_completes(client, monkeypatch):
    c, _ = client
    seen = []

    async def fake_audit(url, *, audit_id=None, progress_callback=None):
        for stage in ("loading_website", "inspecting_structure", "analyzing_performance", "checking_accessibility", "evaluating_seo", "inspecting_responsiveness"):
            seen.append(stage)
            await progress_callback(stage)
        status = {name: CheckResult(status="ok", metrics={"performance_score": 80} if name == "performance" else {}) for name in ("performance", "ui_ux", "responsiveness", "seo", "accessibility")}
        status["accessibility"] = CheckResult(status="unavailable", reason="check failed safely")
        return AuditFindings(scan=ScanResult(audit_id=audit_id, requested_url=url, final_url=url, title="Example"), category_status=status)

    monkeypatch.setattr(audit_runner, "audit", fake_audit)
    response = c.post("/api/audits", json={"url": "https://example.com"})
    audit_id = response.json()["audit_id"]
    status = c.get(f"/api/audits/{audit_id}/status").json()
    assert status["status"] == "completed"
    assert seen == ["loading_website", "inspecting_structure", "analyzing_performance", "checking_accessibility", "evaluating_seo", "inspecting_responsiveness"]
    result = c.get(f"/api/audits/{audit_id}").json()
    assert result["category_scores"]["accessibility"]["score"] is None
    assert result["excluded_categories"][0]["category"] == "accessibility"


def test_screenshot_rejects_traversal_and_unknown_viewports(client):
    c, _ = client
    audit_id = c.post("/api/audits", json={"url": "https://example.com"}).json()["audit_id"]
    assert c.get(f"/api/audits/{audit_id}/screenshots/../secret").status_code in (404, 422)
    assert c.get(f"/api/audits/{audit_id}/screenshots/unknown").status_code == 404


def test_startup_recovery_fails_orphaned_jobs(client):
    c, factory = client
    with factory() as db:
        db.add(Audit(id="3f4935c4-1a0b-4515-9ba1-83f345973df2", website_url="https://example.com", status="running", stage="analyzing_performance", stage_index=4))
        db.commit()
    audit_runner.recover_orphans()
    status = c.get("/api/audits/3f4935c4-1a0b-4515-9ba1-83f345973df2/status").json()
    assert status["status"] == "failed" and status["error"]["code"] == "server_restarted"


@pytest.mark.asyncio
async def test_broken_site_pipeline_stored_score_recomputes(client, monkeypatch):
    _, factory = client
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "true")
    fixture_html = Path(__file__).parent / "fixtures" / "broken_site" / "index.html"
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = fixture_html.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server_obj = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server_obj.serve_forever, daemon=True)
    thread.start()
    try:
        import uuid
        audit_id = str(uuid.uuid4())
        with factory() as db:
            db.add(Audit(id=audit_id, website_url=f"http://127.0.0.1:{server_obj.server_port}", status="queued", stage="initializing", stage_index=1))
            db.commit()
        await audit_runner.run_audit(audit_id)
        with factory() as db:
            row = db.get(Audit, audit_id)
            assert row.status == "completed"
            from app.schemas.audit import Issue
            stored_status = row.metrics_json.pop("_category_status")
            fresh = score_findings(AuditFindings(scan=ScanResult.model_validate(row.scan_json), issues=[Issue(id=i.issue_id, category=i.category, severity=i.severity, title=i.title, description=i.description, evidence=i.evidence_json, impact=i.impact, recommendation=i.recommendation, source=i.source, confidence=i.confidence) for i in row.issues], metrics=row.metrics_json, category_status={k: CheckResult(status=v["status"], reason=v.get("reason"), metrics=v.get("metrics", {})) for k, v in stored_status.items()}))
            assert fresh.overall_score == row.overall_score
    finally:
        server_obj.shutdown()
        server_obj.server_close()
        thread.join(timeout=2)
