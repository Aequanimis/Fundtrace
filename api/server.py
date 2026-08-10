"""Thin local FastAPI bridge for the stable FundTrace analysis workflow."""

from __future__ import annotations

import os
import re
import json
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.presentation import build_presentation
from api.runtime_identity import get_runtime_identity


ROOT = Path(__file__).resolve().parents[1]
FUNDS_DIR = ROOT / "funds"
OUTPUT_DIR = ROOT / "output"
FRONTEND_DIST = ROOT / "frontend" / "dist"
RUN_ANALYSIS = ROOT / "run_analysis.py"
FETCH_FUND = ROOT / "fetch_fund_manual.py"
FUND_CODE_RE = re.compile(r"^\d{6}$")
REQUIRED_LOCAL_FILES = ("nav.csv", "holdings.csv")
DOWNLOAD_ALLOWLIST = {"report.md", "weekly_positions.csv", "diagnostics.csv"}


class AnalyzeRequest(BaseModel):
    fund_code: str = Field(pattern=r"^\d{6}$")
    update_data: bool = True


@dataclass
class JobRecord:
    job_id: str
    fund_code: str
    update_data: bool
    status: str = "queued"
    message: str = "任务已加入队列"
    created_at: float = 0.0
    updated_at: float = 0.0
    analysis_seconds: float | None = None
    can_use_local_data: bool = False
    error_stage: str | None = None
    error_code: str | None = None

    def public(self) -> dict:
        end = self.updated_at if self.status in {"complete", "error"} else time.monotonic()
        payload = asdict(self)
        payload["elapsed_seconds"] = round(max(0.0, end - self.created_at), 1)
        payload.pop("created_at")
        payload.pop("updated_at")
        payload.pop("update_data")
        return payload


app = FastAPI(title="FundTrace Local Bridge", version="1.0.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
JOBS: dict[str, JobRecord] = {}
LAST_ANALYSIS_SECONDS: dict[str, float] = {}
JOB_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fundtrace-ui")


def _has_local_data(code: str) -> bool:
    fund_dir = FUNDS_DIR / code
    return all((fund_dir / filename).is_file() for filename in REQUIRED_LOCAL_FILES)


def _set_job(job_id: str, **changes) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time.monotonic()


def execute_command(command: list[str], log_path: Path, timeout: int = 7200) -> subprocess.CompletedProcess:
    """Execute an explicit argv list; user input never reaches a shell."""
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    result = subprocess.run(
        list(command), cwd=ROOT, shell=False, capture_output=True, env=env, timeout=timeout
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes((result.stdout or b"") + b"\n[stderr]\n" + (result.stderr or b""))
    return result


def parse_fetch_error(result: subprocess.CompletedProcess) -> dict:
    def decoded(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    text = decoded(result.stdout) + "\n" + decoded(result.stderr)
    matches = re.findall(r"FETCH_ERROR_JSON\s+(\{.*\})", text)
    if matches:
        try:
            payload = json.loads(matches[-1])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
    return {
        "stage": "OTHER",
        "code": "PUBLIC_FUND_FETCH_FAILED",
        "message": "公开基金数据获取失败",
    }


def run_analysis_job(job_id: str) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        code = job.fund_code
        update_data = job.update_data
    log_path = OUTPUT_DIR / code / f"ui_job_{job_id}.log"
    try:
        if update_data:
            _set_job(job_id, status="fetching", message="正在更新公开基金数据")
            fetch = execute_command([sys.executable, str(FETCH_FUND), code], log_path)
            if fetch.returncode != 0:
                local_available = _has_local_data(code)
                error = parse_fetch_error(fetch)
                _set_job(
                    job_id,
                    status="error",
                    message=error.get("message") or "公开基金数据获取失败",
                    can_use_local_data=local_available,
                    error_stage=error.get("stage") or "OTHER",
                    error_code=error.get("code") or "PUBLIC_FUND_FETCH_FAILED",
                )
                return
        if not _has_local_data(code):
            _set_job(job_id, status="error", message="暂时无法分析该基金")
            return

        _set_job(job_id, status="analyzing", message="正在计算周频行业暴露")
        analysis_started = time.monotonic()
        analysis = execute_command([sys.executable, str(RUN_ANALYSIS), code], log_path)
        analysis_seconds = time.monotonic() - analysis_started
        if analysis.returncode != 0:
            _set_job(job_id, status="error", message="分析未能完成，请稍后重试")
            return

        _set_job(job_id, status="rendering", message="正在生成分析报告", analysis_seconds=analysis_seconds)
        build_presentation(code, OUTPUT_DIR, analysis_seconds)
        LAST_ANALYSIS_SECONDS[code] = analysis_seconds
        _set_job(
            job_id,
            status="complete",
            message="分析完成",
            analysis_seconds=analysis_seconds,
        )
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="error", message="分析等待时间过长，请稍后重试")
    except Exception:
        _set_job(job_id, status="error", message="分析未能完成，请检查本地数据")


def submit_job(job_id: str) -> None:
    EXECUTOR.submit(run_analysis_job, job_id)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "host": "127.0.0.1", **get_runtime_identity()}


@app.post("/api/analyze", status_code=202)
def analyze(request: AnalyzeRequest) -> dict:
    code = request.fund_code
    if not FUND_CODE_RE.fullmatch(code):
        raise HTTPException(status_code=422, detail="请输入6位基金代码")
    job_id = uuid.uuid4().hex
    now = time.monotonic()
    with JOB_LOCK:
        JOBS[job_id] = JobRecord(
            job_id=job_id,
            fund_code=code,
            update_data=request.update_data,
            created_at=now,
            updated_at=now,
        )
    submit_job(job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job.public()


@app.get("/api/results/{fund_code}")
def results(fund_code: str) -> dict:
    if not FUND_CODE_RE.fullmatch(fund_code):
        raise HTTPException(status_code=422, detail="请输入6位基金代码")
    try:
        return build_presentation(
            fund_code, OUTPUT_DIR, LAST_ANALYSIS_SECONDS.get(fund_code)
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="尚无可用分析结果") from None
    except (ValueError, OSError):
        raise HTTPException(status_code=500, detail="结果文件暂时无法读取") from None


@app.get("/api/downloads/{fund_code}/{filename}")
def download(fund_code: str, filename: str):
    if not FUND_CODE_RE.fullmatch(fund_code) or filename not in DOWNLOAD_ALLOWLIST:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = OUTPUT_DIR / fund_code / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=f"FundTrace_{fund_code}_{filename}")


@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="Frontend build is not available")
    candidate = (FRONTEND_DIST / full_path).resolve()
    dist = FRONTEND_DIST.resolve()
    if candidate.is_file() and dist in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index)


def run_local() -> None:
    import uvicorn

    port = int(os.environ.get("FUNDTRACE_PORT", "8765"))
    uvicorn.run("api.server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    run_local()
