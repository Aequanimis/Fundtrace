"""Run the local FundTrace server with UTF-8 console and file logging."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEALTH_URL = "http://127.0.0.1:8765/api/health"
HOME_URL = "http://127.0.0.1:8765/"
CTRL_C_EXIT_CODES = {-1073741510, 3221225786}


def append_text(log_path: Path, text: str) -> None:
    for _ in range(20):
        try:
            with log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            return
        except PermissionError:
            time.sleep(0.05)


def append_log(log_path: Path, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_text(log_path, f"[{timestamp}] {message}\n")


def forward_output(stream, log_path: Path) -> None:
    for line in iter(stream.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()
        append_text(log_path, line)


def wait_for_http(process: subprocess.Popen[str], url: str, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return None


def read_health_payload(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def wait_for_expected_runtime(
    process: subprocess.Popen[str], url: str, expected_commit: str, timeout: float
) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        payload = read_health_payload(url)
        if payload and payload.get("status") == "ok" and payload.get("app") == "FundTrace":
            if expected_commit in {"", "unknown"} or payload.get("git_commit") == expected_commit:
                return payload
        time.sleep(0.25)
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configured_log = os.environ.get("FUNDTRACE_STARTUP_LOG")
    log_path = Path(configured_log).resolve() if configured_log else ROOT / "logs" / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    expected_commit = os.environ.get("FUNDTRACE_GIT_COMMIT", "unknown")
    append_log(log_path, "stage=fastapi_process command=python -m api.server")
    process = subprocess.Popen(
        [sys.executable, "-m", "api.server"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    output_thread = threading.Thread(
        target=forward_output, args=(process.stdout, log_path), daemon=True
    )
    output_thread.start()

    payload = wait_for_expected_runtime(process, HEALTH_URL, expected_commit, timeout=30)
    if payload is None:
        append_log(
            log_path,
            f"stage=healthcheck FASTAPI_HEALTHCHECK_FAILED expected_commit={expected_commit}",
        )
        if process.poll() is None:
            process.terminate()
        output_thread.join(timeout=5)
        return process.wait(timeout=10) or 1

    append_log(
        log_path,
        "stage=healthcheck FASTAPI_HEALTHCHECK_OK "
        f"status=200 app={payload.get('app')} git_commit={payload.get('git_commit')} "
        f"branch={payload.get('branch')}",
    )
    home_status = wait_for_http(process, HOME_URL, timeout=5)
    append_log(log_path, f"stage=homepage HTTP_STATUS={home_status}")
    print("[FundTrace] FASTAPI_HEALTHCHECK_OK (HTTP 200)", flush=True)
    if home_status == 200 and os.environ.get("FUNDTRACE_OPEN_BROWSER") == "1":
        webbrowser.open(HOME_URL)
        append_log(log_path, "stage=browser_open URL=http://127.0.0.1:8765/")

    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        append_log(log_path, "stage=fastapi_stop user_interrupt=true exit_code=0")
        return 0
    finally:
        output_thread.join(timeout=5)

    if return_code in CTRL_C_EXIT_CODES:
        append_log(log_path, "stage=fastapi_stop user_interrupt=true exit_code=0")
        return 0
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
