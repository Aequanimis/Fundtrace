#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated Phase A calibration worker (no production parameter writes)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lib.calibrate_phase_a import (  # noqa: E402
    atomic_write_json,
    files_sha256,
    run_phase_a_grid,
)
from lib.regress import build_stock_factors, index_to_returns, nav_to_returns  # noqa: E402
from lib.simulate import SimulatedPortfolio  # noqa: E402
from run_analysis import extract_real_holdings, load_base, load_fund  # noqa: E402


def _test_hang_if_requested(output_dir: Path):
    seconds = float(os.environ.get("FUNDTRACE_CALIBRATION_TEST_HANG_SECONDS", "0") or 0)
    if seconds <= 0:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        shell=False,
    )
    (output_dir / "test_child_pid.txt").write_text(str(child.pid), encoding="ascii")
    print(f"TEST_HANG worker={os.getpid()} child={child.pid}", flush=True)
    time.sleep(seconds)


def _identity(code, factor_source, nav, hold):
    fund_dir = ROOT / "funds" / code
    base_files = sorted(path for path in (ROOT / "base").iterdir() if path.is_file())
    code_files = [
        ROOT / "lib" / "regress.py",
        ROOT / "lib" / "calibrate.py",
        ROOT / "lib" / "calibrate_phase_a.py",
        ROOT / "calibration_worker.py",
        ROOT / "run_analysis.py",
    ]
    nav_latest = str(pd.to_datetime(nav["date"], errors="coerce").max().date())
    holding_dates = []
    for column in hold.columns:
        if "季度" in str(column) or "报告" in str(column) or str(column).lower() == "period":
            holding_dates.extend(pd.to_datetime(hold[column], errors="coerce").dropna().tolist())
    holdings_latest = str(max(holding_dates).date()) if holding_dates else "unknown"
    return {
        "factor_source": factor_source,
        "nav_latest_date": nav_latest,
        "holdings_latest_date": holdings_latest,
        "nav_hash": files_sha256([fund_dir / "nav.csv"]),
        "holdings_hash": files_sha256([fund_dir / "holdings.csv"]),
        "base_hash": files_sha256(base_files),
        "code_version_identifier": files_sha256(code_files),
    }


def main():
    parser = argparse.ArgumentParser(description="FundTrace Phase A calibration worker")
    parser.add_argument("code", nargs="?", default="161005")
    parser.add_argument("--stock-level", action="store_true")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    code = args.code.zfill(6)
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "output" / code
    started = time.monotonic()
    _test_hang_if_requested(output_dir)

    maximum = float(os.environ.get("FUNDTRACE_CALIBRATION_TIMEOUT_SECONDS", "300") or 300)
    safe_stop = 285.0 if maximum >= 300 else max(maximum - 1.0, 0.1)

    index_long, stock2sw = load_base()
    nav, hold, allocation = load_fund(code)
    portfolio = SimulatedPortfolio(hold, allocation, stock2sw, verbose=False)
    sim_mat, _ = portfolio.build_all()
    real_holdings = extract_real_holdings(hold, portfolio)
    if real_holdings.empty:
        raise SystemExit("没有真实全持股，无法执行 Phase A 标定。")
    fund_ret, _ = nav_to_returns(nav)
    factor_ret = index_to_returns(index_long)
    factor_source = "index_proxy"
    anchor_mults = (None, 2.5)

    if args.stock_level:
        if portfolio.mode != "FULL":
            raise SystemExit("stock_level 标定仅支持 FULL 模式。")
        recipe, recipe_info = portfolio.build_stock_recipe()
        kline_path = ROOT / "base" / "stock_klines.csv"
        if not kline_path.exists():
            raise SystemExit(f"缺少全局个股 K 线缓存：{kline_path}")
        klines = pd.read_csv(kline_path, dtype={"date": str, "code": str, "close": float})
        klines["date"] = pd.to_datetime(klines["date"])
        stock_returns = (
            klines.pivot_table(index="date", columns="code", values="close", aggfunc="last")
            .sort_index().pct_change().dropna(how="all")
        )
        factor_ret = build_stock_factors(
            stock_returns, recipe, recipe_info, sorted(portfolio.hold["period"].unique())
        )
        factor_source = "stock_level"
        anchor_mults = (None,)

    result = run_phase_a_grid(
        fund_ret=fund_ret,
        factor_ret=factor_ret,
        sim_mat=sim_mat,
        real_holdings=real_holdings,
        stock2sw=stock2sw,
        output_dir=output_dir,
        fund_code=code,
        base_identity=_identity(code, factor_source, nav, hold),
        anchor_mults=anchor_mults,
        max_calibration_seconds=maximum,
        safe_stop_seconds=safe_stop,
        start_monotonic=started,
        verbose=True,
    )
    print("PHASE_A_RESULT_JSON=" + json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
