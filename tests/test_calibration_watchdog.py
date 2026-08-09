import json
import os
import subprocess
import time
from pathlib import Path

import pandas as pd

from lib.calibration_watchdog import run_calibration_watchdog


ROOT = Path(__file__).resolve().parents[1]


def _pid_exists(pid):
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            shell=False,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_five_second_watchdog_kills_worker_tree_and_saves_state(tmp_path):
    started = time.monotonic()
    result = run_calibration_watchdog(
        "161005",
        ROOT,
        timeout_seconds=5,
        output_dir=tmp_path,
        extra_env={"FUNDTRACE_CALIBRATION_TEST_HANG_SECONDS": "60"},
    )
    elapsed = time.monotonic() - started

    assert 4.5 <= elapsed < 12
    assert result["status"] == "TIMEOUT_HARD_KILL"
    assert result["hard_watchdog"] is True
    assert result["residual_worker_process"] is False
    assert (tmp_path / "calibration_checkpoint.csv").is_file()
    assert (tmp_path / "calibration_meta.json").is_file()
    assert (tmp_path / "performance_timeout_report.md").is_file()
    assert not (tmp_path / "best_params.json").exists()
    assert not (tmp_path / "best_params_phaseA_candidate.json").exists()

    checkpoint = pd.read_csv(tmp_path / "calibration_checkpoint.csv")
    assert checkpoint.empty
    meta = json.loads((tmp_path / "calibration_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "TIMEOUT_HARD_KILL"

    child_pid = int((tmp_path / "test_child_pid.txt").read_text(encoding="ascii"))
    worker_pid = result["worker_pid"]
    for _ in range(20):
        if not _pid_exists(child_pid) and not _pid_exists(worker_pid):
            break
        time.sleep(0.1)
    assert not _pid_exists(child_pid)
    assert not _pid_exists(worker_pid)
