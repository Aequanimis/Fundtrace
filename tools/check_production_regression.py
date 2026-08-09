#!/usr/bin/env python3
"""Run the stable quick analysis and compare it with the production baseline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = ROOT / "tests" / "baseline" / "v4_a2_1_production"


def _weekly(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, errors="raise")
    return frame.apply(pd.to_numeric, errors="raise")


def compare_weekly(current_path: Path, baseline_path: Path) -> dict:
    current = _weekly(current_path)
    baseline = _weekly(baseline_path)
    extra = sorted(set(current.columns) - set(baseline.columns))
    missing = sorted(set(baseline.columns) - set(current.columns))
    index_equal = current.index.equals(baseline.index)
    columns_equal = list(current.columns) == list(baseline.columns)

    common = baseline.columns.intersection(current.columns)
    if index_equal and len(common):
        difference = np.abs(current[common].to_numpy() - baseline[common].to_numpy())
        max_abs_diff = float(difference.max())
    else:
        max_abs_diff = float("inf")

    top5_matches = 0
    top1_matches = 0
    if index_equal:
        union = baseline.columns.union(current.columns)
        left = baseline.reindex(columns=union, fill_value=0.0).to_numpy()
        right = current.reindex(columns=union, fill_value=0.0).to_numpy()
        for reference_row, current_row in zip(left, right):
            top1_matches += int(union[reference_row.argmax()] == union[current_row.argmax()])
            reference_top5 = set(union[np.argsort(reference_row)[-5:]])
            current_top5 = set(union[np.argsort(current_row)[-5:]])
            top5_matches += int(reference_top5 == current_top5)

    return {
        "index_equal": index_equal,
        "columns_equal": columns_equal,
        "industry_column_count": len(current.columns),
        "baseline_industry_column_count": len(baseline.columns),
        "extra_columns": extra,
        "missing_columns": missing,
        "max_abs_diff": max_abs_diff,
        "top1_matches": top1_matches,
        "top5_matches": top5_matches,
        "rows": len(baseline),
        "has_coal": "煤炭" in current.columns,
    }


def compare_diagnostics(current_path: Path, baseline_path: Path) -> dict:
    current = pd.read_csv(current_path, index_col=0)
    baseline = pd.read_csv(baseline_path, index_col=0)
    index_equal = current.index.equals(baseline.index)
    if not index_equal:
        return {"index_equal": False, "sum_beta_max_abs_diff": float("inf")}
    delta = np.abs(
        pd.to_numeric(current["sum_beta"]).to_numpy()
        - pd.to_numeric(baseline["sum_beta"]).to_numpy()
    )
    return {"index_equal": True, "sum_beta_max_abs_diff": float(delta.max())}


def run_quick_analysis(code: str) -> float:
    environment = os.environ.copy()
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, str(ROOT / "run_analysis.py"), code],
        cwd=ROOT,
        env=environment,
        shell=False,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if process.returncode:
        raise SystemExit(process.returncode)
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fund_code", nargs="?", default="161005")
    parser.add_argument("--threshold", type=float, default=1e-12)
    parser.add_argument("--no-run", action="store_true", help="compare existing output only")
    args = parser.parse_args()
    if not args.fund_code.isdigit() or len(args.fund_code) != 6:
        parser.error("fund_code must contain exactly six digits")
    if args.fund_code != "161005":
        parser.error("the current production baseline is available only for 161005")

    elapsed = None if args.no_run else run_quick_analysis(args.fund_code)
    result_dir = ROOT / "output" / args.fund_code
    weekly = compare_weekly(
        result_dir / "weekly_positions.csv", BASELINE_ROOT / "weekly_positions.csv"
    )
    diagnostics = compare_diagnostics(
        result_dir / "diagnostics.csv", BASELINE_ROOT / "diagnostics.csv"
    )
    passed = (
        weekly["index_equal"]
        and weekly["columns_equal"]
        and weekly["max_abs_diff"] <= args.threshold
        and weekly["top5_matches"] == weekly["rows"]
        and diagnostics["sum_beta_max_abs_diff"] <= args.threshold
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "model": "v4-a2.1-stable",
        "fund_code": args.fund_code,
        "analysis_seconds": elapsed,
        "threshold": args.threshold,
        "weekly_positions": weekly,
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
