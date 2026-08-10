import subprocess
import time

from fastapi.testclient import TestClient

from api import server


def setup_function():
    server.JOBS.clear()
    server.LAST_ANALYSIS_SECONDS.clear()


def test_health_and_invalid_code_rejection(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(
        server,
        "get_runtime_identity",
        lambda: {
            "app": "FundTrace",
            "git_commit": "1ccbb8f",
            "branch": "fix/new-fund-fetch",
            "project_root": "Fundtrace_mvp_pre_ui",
            "python_executable": ".venv/Scripts/python.exe",
        },
    )
    health = client.get("/api/health").json()
    assert health["host"] == "127.0.0.1"
    assert health["app"] == "FundTrace"
    assert health["git_commit"] == "1ccbb8f"
    assert health["project_root"] == "Fundtrace_mvp_pre_ui"
    for invalid in ("16100", "1610057", "../161005", "161005;calc"):
        assert client.post("/api/analyze", json={"fund_code": invalid}).status_code == 422
    assert server.JOBS == {}


def test_valid_job_creation_and_status(monkeypatch):
    monkeypatch.setattr(server, "submit_job", lambda job_id: None)
    client = TestClient(server.app)
    response = client.post("/api/analyze", json={"fund_code": "161005", "update_data": False})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["fund_code"] == "161005"


def test_completed_job_elapsed_time_is_frozen(monkeypatch):
    job = server.JobRecord(
        "job", "161005", False, status="complete", created_at=100.0, updated_at=116.3
    )
    monkeypatch.setattr(server.time, "monotonic", lambda: 999.0)
    assert job.public()["elapsed_seconds"] == 16.3


def test_results_success_and_missing(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(server, "build_presentation", lambda *args: {"fund_code": "161005"})
    assert client.get("/api/results/161005").json() == {"fund_code": "161005"}

    def missing(*args):
        raise FileNotFoundError

    monkeypatch.setattr(server, "build_presentation", missing)
    assert client.get("/api/results/161005").status_code == 404


def test_frontend_serves_fresh_index_and_rejects_stale_assets(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>FundTrace</title>", encoding="utf-8")
    (assets / "index-current.js").write_text("export default 'current'", encoding="utf-8")
    monkeypatch.setattr(server, "FRONTEND_DIST", dist)
    client = TestClient(server.app)

    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-cache"

    current = client.get("/assets/index-current.js")
    assert current.status_code == 200
    assert current.headers["cache-control"] == "public, max-age=31536000, immutable"

    stale = client.get("/assets/ResultsDashboard-stale.js")
    assert stale.status_code == 404
    assert stale.json()["detail"] == "Frontend asset not found"


def test_update_failure_offers_local_fallback(tmp_path, monkeypatch):
    fund_dir = tmp_path / "funds" / "161005"
    fund_dir.mkdir(parents=True)
    for filename in server.REQUIRED_LOCAL_FILES:
        (fund_dir / filename).write_text("x", encoding="utf-8")
    monkeypatch.setattr(server, "FUNDS_DIR", tmp_path / "funds")
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        server,
        "execute_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b"", b"failed"),
    )
    now = time.monotonic()
    server.JOBS["job"] = server.JobRecord("job", "161005", True, created_at=now, updated_at=now)
    server.run_analysis_job("job")
    assert server.JOBS["job"].status == "error"
    assert server.JOBS["job"].message == "公开基金数据获取失败"
    assert server.JOBS["job"].can_use_local_data is True
    assert server.JOBS["job"].error_stage == "OTHER"
    assert server.JOBS["job"].error_code == "PUBLIC_FUND_FETCH_FAILED"


def test_execute_command_always_disables_shell(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    command = ["python", "run_analysis.py", "161005"]
    server.execute_command(command, tmp_path / "job.log")
    assert captured["command"] == command
    assert captured["shell"] is False
