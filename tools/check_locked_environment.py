#!/usr/bin/env python3
"""Check the active Python environment against requirements-lock.txt."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)$")


def read_lock(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ValueError(f"Unsupported lock entry: {line}")
        pins[match.group(1)] = match.group(2)
    if not pins:
        raise ValueError("Dependency lock is empty")
    return pins


def check_environment(path: Path) -> dict:
    expected = read_lock(path)
    installed: dict[str, str | None] = {}
    mismatches: dict[str, dict[str, str | None]] = {}
    for package, version in expected.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        installed[package] = actual
        if actual != version:
            mismatches[package] = {"expected": version, "actual": actual}
    return {
        "lock_path": str(path),
        "verified": not mismatches,
        "expected": expected,
        "installed": installed,
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "requirements-lock.txt")
    args = parser.parse_args()
    result = check_environment(args.lock.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["verified"] else 1)


if __name__ == "__main__":
    main()
