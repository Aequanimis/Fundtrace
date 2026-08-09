#!/usr/bin/env python3
"""Collect a reproducibility manifest without changing model inputs or outputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARAMETERS = {
    "window": 120,
    "half_life": 40,
    "alpha": 1e-6,
    "anchor_mult": None,
    "equity_cap": "auto",
    "factor_mode": "index_proxy",
    "calibrate": False,
}
SOURCE_FILES = [
    "run_analysis.py",
    "lib/solver.py",
    "lib/regress.py",
    "lib/calibrate.py",
    "lib/simulate.py",
    "lib/taxonomy.py",
]
PACKAGE_NAMES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "sklearn": "scikit-learn",
    "matplotlib": "matplotlib",
    "akshare": "akshare",
    "requests": "requests",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for label, distribution in PACKAGE_NAMES.items():
        try:
            versions[label] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[label] = None
    return versions


def csv_metadata(path: Path) -> dict:
    frame = pd.read_csv(path, nrows=5)
    return {
        "rows": sum(1 for _ in path.open("rb")) - 1,
        "columns": len(frame.columns),
        "column_names": list(frame.columns),
    }


def file_metadata(path: Path, *, csv: bool = False) -> dict:
    relative = path.relative_to(ROOT).as_posix()
    data = {
        "path": relative,
        "exists": path.is_file(),
    }
    if not path.is_file():
        return data
    data.update({"size_bytes": path.stat().st_size, "sha256": sha256(path)})
    if csv:
        data.update(csv_metadata(path))
    return data


def output_schema(path: Path, *, industry_output: bool = False) -> dict | None:
    if not path.is_file():
        return None
    frame = pd.read_csv(path)
    date_column = "date" if "date" in frame.columns else frame.columns[0]
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    value_columns = [str(column) for column in frame.columns if column != date_column]
    result = {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "rows": len(frame),
        "columns": len(frame.columns),
        "value_columns": value_columns,
        "date_min": dates.min().strftime("%Y-%m-%d") if len(dates) else None,
        "date_max": dates.max().strftime("%Y-%m-%d") if len(dates) else None,
    }
    if industry_output:
        result["industry_column_count"] = len(value_columns)
        result["industry_columns"] = value_columns
    return result


def git_metadata() -> dict:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()

    try:
        return {"commit": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current")}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "branch": None}


def build_manifest(code: str) -> dict:
    input_specs = [
        (ROOT / "base" / "sw_industry_index.csv", "run_analysis.load_base", True),
        (ROOT / "base" / "stock_industry_map.csv", "run_analysis.load_base", True),
        (ROOT / "funds" / code / "nav.csv", "run_analysis.load_fund", True),
        (ROOT / "funds" / code / "holdings.csv", "run_analysis.load_fund", True),
        (ROOT / "funds" / code / "industry_alloc.csv", "run_analysis.load_fund", False),
    ]
    inputs = []
    for path, loader, required in input_specs:
        item = file_metadata(path, csv=True)
        item.update({"loader": loader, "required": required, "used_by_default_analysis": True})
        inputs.append(item)

    return {
        "manifest_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fund_code": code,
        "git": git_metadata(),
        "environment": {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "packages": package_versions(),
        },
        "parameters": DEFAULT_PARAMETERS,
        "source_files": [file_metadata(ROOT / relative) for relative in SOURCE_FILES],
        "input_trace": inputs,
        "conditional_inputs_not_used": [
            {
                "path": "base/stock_klines.csv",
                "condition": "only with --stock-level",
                "used_by_default_analysis": False,
            }
        ],
        "output_schema": {
            "weekly_positions": output_schema(
                ROOT / "output" / code / "weekly_positions.csv", industry_output=True
            ),
            "diagnostics": output_schema(ROOT / "output" / code / "diagnostics.csv"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fund_code", nargs="?", default="161005")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.fund_code.isdigit() or len(args.fund_code) != 6:
        parser.error("fund_code must contain exactly six digits")
    output = args.output or ROOT / "output" / args.fund_code / "reproducibility_manifest.json"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_manifest(args.fund_code), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
