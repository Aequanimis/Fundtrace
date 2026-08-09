# -*- coding: utf-8 -*-
"""CLI 集成冒烟测试：覆盖三个入口 + 参数传递层。

这是测试金字塔的顶层——lib/ 里的单元测试各自过，
但这些函数被组装成 run_analysis.py 的那一层最容易在
签名变更/默认值覆盖时崩溃，而此类崩溃不会出现在单元测试中
（v1 NameError: nav_col、v3 TypeError: anchor_mults=None 均在此层）。

三个场景：
  1. 默认参数（index_proxy，无标定）
  2. --calibrate（TS-CV 参数标定）
  3. --stock-level（穿透路径，仅 FULL 模式）

每个场景只验证"能跑完，不崩溃"，不做结果正确性断言。
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CODE = sys.argv[1] if len(sys.argv) > 1 else "161005"


def run_and_check(args, label):
    cmd = [PY, os.path.join(ROOT, "run_analysis.py"), CODE] + args
    print(f"\n{'='*60}")
    print(f"[{label}] {' '.join(cmd)}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"  exit={result.returncode}  {status}")
    if not ok:
        # print last 20 lines of stderr
        lines = result.stderr.strip().split("\n")
        print("  stderr tail:")
        for line in lines[-20:]:
            print(f"    {line}")
    return ok


def main():
    results = {}

    # 1. 默认参数（快）
    results["default"] = run_and_check(
        ["--window", "120", "--half-life", "40", "--alpha", "1e-6"],
        "default")

    # 2. calibrate（TS-CV，内存开销大，可选）
    if os.environ.get("SMOKE_CALIBRATE"):
        results["calibrate"] = run_and_check(
            ["--calibrate", "--window", "120", "--half-life", "40",
             "--alpha", "1e-6"],
            "calibrate")
    else:
        print("\n[calibrate] SKIP — set SMOKE_CALIBRATE=1 to run (heavy)")

    # 3. stock_level（需有 K 线缓存）
    kline_path = os.path.join(ROOT, "base", "stock_klines.csv")
    if os.path.exists(kline_path):
        results["stock_level"] = run_and_check(
            ["--stock-level", "--window", "120", "--half-life", "40",
             "--alpha", "1e-6"],
            "stock_level")
    else:
        print(f"\n[stock_level] SKIP — {kline_path} 不存在，请先 python fetch_stock_klines.py 161005")

    print(f"\n{'='*60}")
    passed = sum(results.values())
    total = len(results)
    print(f"CLI smoke: {passed}/{total} passed")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
