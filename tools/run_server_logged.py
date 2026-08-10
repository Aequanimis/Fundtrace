"""Run the local FundTrace server with UTF-8 console and file logging."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEALTH_URL = "http://127.0.0.1:8765/api/health"
HOME_URL = "http://127.0.0.1:8765/"
CTRL_C_EXIT_CODES = {-1073741510, 3221225786}


def append_log(log_path: Path, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def forward_output(stream, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        for line in iter(stream.readline, ""):
            sys.stdout.write(line)
            sys.stdout.flush()
            handle.write(line)
            handle.flush()


def wait_for_http(process: subprocess.Popen[str], url: str, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return None


def main() -> int:
    log_path = ROOT / "logs" / "startup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
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

    health_status = wait_for_http(process, HEALTH_URL, timeout=30)
    if health_status != 200:
        append_log(log_path, f"stage=healthcheck FASTAPI_HEALTHCHECK_FAILED status={health_status}")
        if process.poll() is None:
            process.terminate()
        output_thread.join(timeout=5)
        return process.wait(timeout=10) or 1

    with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    append_log(
        log_path,
        f"stage=healthcheck FASTAPI_HEALTHCHECK_OK status=200 host={payload.get('host')}",
    )
    home_status = wait_for_http(process, HOME_URL, timeout=5)
    append_log(log_path, f"stage=homepage HTTP_STATUS={home_status}")
    print("[FundTrace] FASTAPI_HEALTHCHECK_OK (HTTP 200)", flush=True)

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
