#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze the B1 legacy equity-cap baseline from already-written outputs.

This helper intentionally never calls the portfolio builder or rolling model.
It reconstructs the historical legacy cap schedule from the frozen simulated
portfolio artifact and diagnostics written by the B1/A2.1 run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.regress import disclosure_align  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(code: str = "161005") -> None:
    code = str(code).zfill(6)
    outdir = ROOT / "output" / code
    baseline_dir = ROOT / "tests" / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    sim_path = outdir / "sim_portfolio.csv"
    diagnostics_path = outdir / "diagnostics.csv"
    weekly_path = outdir / "weekly_positions.csv"
    report_path = outdir / "report.md"
    required = (sim_path, diagnostics_path, weekly_path, report_path)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing frozen B1 artifact(s): {missing}")

    sim = pd.read_csv(sim_path, index_col=0)
    sim.index = pd.to_datetime(sim.index)
    sim = sim.sort_index()
    diagnostics = pd.read_csv(diagnostics_path)
    diagnostics["date"] = pd.to_datetime(diagnostics["date"])
    sim_disc = disclosure_align(sim)
    shifted_to_period = dict(zip(sim_disc.index, sim.index))

    rows = []
    for date, sum_beta in diagnostics[["date", "sum_beta"]].itertuples(index=False):
        available = sim_disc.index[sim_disc.index + pd.Timedelta(days=30) <= date]
        if len(available):
            shifted = available[-1]
            prior = sim_disc.loc[shifted]
            cap = min(float(prior.sum()) * 1.05, 0.98)
            period = shifted_to_period[shifted]
            latest_prior_period = pd.Timestamp(period).strftime("%Y-%m-%d")
        else:
            cap = 0.95
            latest_prior_period = ""
        rows.append({
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "sum_beta": float(sum_beta),
            "legacy_cap": float(cap),
            "latest_prior_period": latest_prior_period,
        })

    baseline = pd.DataFrame(rows)
    if len(baseline) != len(diagnostics) or baseline["legacy_cap"].isna().any():
        raise RuntimeError("Legacy baseline freeze failed completeness checks")
    baseline.to_csv(
        baseline_dir / "phaseB2_legacy_equity_cap.csv", index=False, encoding="utf-8-sig"
    )

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    files = {path.name: sha256(path) for path in (weekly_path, diagnostics_path, report_path)}
    precheck = {
        "commit": commit,
        "fund_code": code,
        "files": files,
        "legacy_equity_cap_rows": int(len(baseline)),
    }
    (baseline_dir / "phaseB2_precheck.json").write_text(
        json.dumps(precheck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Frozen {len(baseline)} legacy weekly cap records at {baseline_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "161005")
