"""Safely resolve an existing local FundTrace process on a Windows port."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


HEALTH_URL = "http://127.0.0.1:{port}/api/health"


def listening_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[-2].upper() != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def health_payload(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL.format(port=port), timeout=2) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def process_details(pid: int) -> dict[str, str | int]:
    if pid <= 0:
        return {}
    command = (
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' -ErrorAction SilentlyContinue; "
        "if ($null -ne $p) { [pscustomobject]@{ "
        "ProcessId = $p.ProcessId; ExecutablePath = $p.ExecutablePath; CommandLine = $p.CommandLine "
        "} | ConvertTo-Json -Compress }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_fundtrace_process(details: dict[str, str | int]) -> bool:
    executable = str(details.get("ExecutablePath") or "").casefold()
    command_line = str(details.get("CommandLine") or "").casefold()
    return "fundtrace" in f"{executable} {command_line}" and "api.server" in command_line


def classify_runtime(
    expected_commit: str,
    payload: dict | None,
    details: list[dict[str, str | int]],
) -> str:
    if not details:
        return "PORT_FREE"
    if payload and payload.get("app") == "FundTrace":
        if expected_commit != "unknown" and payload.get("git_commit") == expected_commit:
            return "CURRENT_RUNTIME_REUSED"
        return "STALE_BACKEND_PROCESS"
    if not all(is_fundtrace_process(item) for item in details):
        return "PORT_8765_OCCUPIED_BY_OTHER_APP"
    return "STALE_BACKEND_PROCESS"


def stop_process_tree(pid: int) -> bool:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0


def wait_for_port_release(port: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not listening_pids(port):
            return True
        time.sleep(0.2)
    return not listening_pids(port)


def emit(status: str, **extra) -> None:
    print("RUNTIME_PORT_GUARD_JSON " + json.dumps({"status": status, **extra}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--expected-commit", default="unknown")
    args = parser.parse_args()

    pids = listening_pids(args.port)
    if not pids:
        emit("PORT_FREE", port=args.port)
        return 0

    details = [process_details(pid) for pid in pids]
    payload = health_payload(args.port)
    classification = classify_runtime(args.expected_commit, payload, details)
    if classification == "CURRENT_RUNTIME_REUSED":
        emit(classification, port=args.port, pids=pids, git_commit=payload.get("git_commit"))
        return 10
    if classification != "STALE_BACKEND_PROCESS":
        emit(classification, port=args.port, pids=pids)
        return 20

    stopped = [pid for pid in pids if stop_process_tree(pid)]
    if stopped and wait_for_port_release(args.port):
        emit("STALE_BACKEND_PROCESS_STOPPED", port=args.port, pids=stopped)
        return 0
    emit("STALE_BACKEND_PROCESS_STOP_FAILED", port=args.port, pids=pids)
    return 21


if __name__ == "__main__":
    raise SystemExit(main())
