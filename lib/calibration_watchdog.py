# -*- coding: utf-8 -*-
"""Parent-process watchdog for the isolated calibration worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from .calibrate_phase_a import atomic_write_csv, atomic_write_json, write_timeout_report


DEFAULT_TIMEOUT_SECONDS = 300.0
CHECKPOINT_COLUMNS = [
    "combo_id", "window", "half_life", "alpha", "anchor_mult",
    "duration_seconds", "elapsed_seconds", "solver_calls", "status", "error",
]


def _terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _read_meta(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_calibration_watchdog(
    code,
    project_root,
    stock_level=False,
    timeout_seconds=None,
    output_dir=None,
    extra_env=None,
):
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir) if output_dir else project_root / "output" / str(code).zfill(6)
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    if timeout_seconds is None:
        timeout_seconds = float(env.get("FUNDTRACE_CALIBRATION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    env["FUNDTRACE_CALIBRATION_TIMEOUT_SECONDS"] = str(timeout_seconds)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        sys.executable,
        str(project_root / "calibration_worker.py"),
        str(code).zfill(6),
        "--output-dir",
        str(output_dir),
    ]
    if stock_level:
        command.append("--stock-level")

    started = time.monotonic()
    process = subprocess.Popen(command, cwd=str(project_root), shell=False, env=env)
    hard_kill = False
    try:
        process.wait(timeout=float(timeout_seconds))
    except subprocess.TimeoutExpired:
        hard_kill = True
        _terminate_tree(process)

    elapsed = time.monotonic() - started
    meta_path = output_dir / "calibration_meta.json"
    meta = _read_meta(meta_path)
    if hard_kill:
        meta.update({
            "status": "TIMEOUT_HARD_KILL",
            "elapsed_seconds": elapsed,
            "completed_combos": int(meta.get("completed_combos", 0)),
            "total_combos": int(meta.get("total_combos", 160)),
            "watchdog_pid": process.pid,
        })
        atomic_write_json(meta, meta_path)
        checkpoint_path = output_dir / "calibration_checkpoint.csv"
        try:
            checkpoint = pd.read_csv(checkpoint_path)
        except (OSError, pd.errors.EmptyDataError):
            checkpoint = pd.DataFrame(columns=CHECKPOINT_COLUMNS)
            atomic_write_csv(checkpoint, checkpoint_path, index=False)
        residual_process = process.poll() is None
        write_timeout_report(
            output_dir,
            checkpoint,
            meta,
            watchdog=True,
            residual_process=residual_process,
        )
        print(
            "本次完整标定未能在5分钟限制内完成，已安全停止。\n"
            "未完成结果不会用于正式分析。\n"
            "快速分析继续使用默认参数或已有有效参数。",
            flush=True,
        )
    elif process.returncode != 0:
        meta.update({"status": "ERROR", "elapsed_seconds": elapsed, "returncode": process.returncode})
        atomic_write_json(meta, meta_path)
    return {
        "status": meta.get("status", "ERROR"),
        "returncode": process.returncode,
        "elapsed_seconds": elapsed,
        "hard_watchdog": hard_kill,
        "worker_pid": process.pid,
        "residual_worker_process": process.poll() is None,
        "completed_combos": int(meta.get("completed_combos", 0)),
        "total_combos": int(meta.get("total_combos", 160)),
    }
