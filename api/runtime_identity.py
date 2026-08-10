"""Privacy-safe identity for a running local FundTrace backend."""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = "unknown"


def _git_value(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return UNKNOWN
    return result.stdout.strip() or UNKNOWN


def _safe_python_executable() -> str:
    executable = Path(sys.executable).resolve()
    try:
        return executable.relative_to(ROOT).as_posix()
    except ValueError:
        return executable.name


@lru_cache(maxsize=1)
def get_runtime_identity() -> dict[str, str]:
    """Return enough data to identify a local build without exposing user paths."""
    return {
        "app": "FundTrace",
        "git_commit": os.environ.get("FUNDTRACE_GIT_COMMIT") or _git_value("rev-parse", "HEAD"),
        "branch": os.environ.get("FUNDTRACE_GIT_BRANCH") or _git_value("branch", "--show-current"),
        "project_root": ROOT.name,
        "python_executable": _safe_python_executable(),
    }
