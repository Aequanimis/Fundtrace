# -*- coding: utf-8 -*-
"""disclosure_align 边界测试：确保季报约束不会在披露日前泄露。

这是前视偏差的最后一道防线——只要有一天没对齐，Q1 季报的真实持仓就会
"提前"进入 Q2 早期的回归约束，对高换手基金会虚增准确度。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.regress import disclosure_align
import pandas as pd


def test_basic_shift():
    """基本移位：Q1 报告期 3/31 → 后移 45 个工作日 ≈ 6月初。"""
    sim = pd.DataFrame(
        {"电子": [0.25], "医药": [0.20]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-03-31")]))
    aligned = disclosure_align(sim, bus_days=45)
    shifted = aligned.index[0]
    # 45 个工作日 ≈ 约 63 个日历日 → 应该在 6 月初
    assert shifted > pd.Timestamp("2025-05-30"), f"shifted too early: {shifted}"
    assert shifted < pd.Timestamp("2025-06-10"), f"shifted too late: {shifted}"
    print("  PASS test_basic_shift:", shifted.date())


def test_no_future_leak():
    """回归在 4 月中旬 → 不应看到 Q1。"""
    sim = pd.DataFrame(
        {"电子": [0.25]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-03-31")]))
    aligned = disclosure_align(sim, bus_days=45)
    # 4月10号：< aligned index → 用 _latest_sim_row (+30d) 也不会拿到
    april10 = pd.Timestamp("2025-04-10")
    # 模拟 _latest_sim_row 的逻辑：index + 30d <= d
    assert not ((aligned.index + pd.Timedelta(days=30)) <= april10).any(), \
        "Q1 不该在 4/10 可获取"
    print("  PASS test_no_future_leak: 4/10 no Q1")


def test_after_disclosure_ok():
    """回归在 7 月中旬 → 应该能看到 Q1。
    
    注意：disclosure_align(+45 工作日) + _latest_sim_row(+30 日历天) 组合滞后
    约 93 天，比实际季报披露时间（~4月底）保守得多，但刻意避免了任何可能的前视。
    """
    sim = pd.DataFrame(
        {"电子": [0.25]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-03-31")]))
    aligned = disclosure_align(sim, bus_days=45)
    july10 = pd.Timestamp("2025-07-10")
    assert (aligned.index + pd.Timedelta(days=30) <= july10).any(), \
        f"Q1 应该在 7/10 可获取 (aligned={aligned.index[0].date()})"
    print(f"  PASS test_after_disclosure_ok: 7/10 sees Q1 (shifted to {aligned.index[0].date()})")


def test_multi_period_boundary():
    """多期：确保 Q1(3/31)、Q2(6/30)、Q3(9/30) 各期不会互相穿透。"""
    periods = [
        pd.Timestamp("2025-03-31"),
        pd.Timestamp("2025-06-30"),
        pd.Timestamp("2025-09-30"),
    ]
    sim = pd.DataFrame(
        {"电子": [0.25, 0.30, 0.28]},
        index=pd.DatetimeIndex(periods))
    aligned = disclosure_align(sim, bus_days=45)

    # 4月 → 只能看到上年 Q4（即什么都不该看到）
    april = pd.Timestamp("2025-04-15")
    avail = aligned.index[aligned.index + pd.Timedelta(days=30) <= april]
    assert len(avail) == 0, f"4月不该看到任何季报约束: {avail}"

    # 8月 → 应该看到 Q1，不该看到 Q2（Q2 aligned ≈ 9月初 +30d ≈ 10月初）
    august = pd.Timestamp("2025-08-15")
    avail = aligned.index[aligned.index + pd.Timedelta(days=30) <= august]
    assert len(avail) >= 1, f"8月应该看到 Q1: {avail}"
    # Q2 aligned index ≈ 9月初，8月不应该看到
    q2_orig_idx = 1  # 第二个原始期
    q2_aligned = aligned.index[q2_orig_idx]
    assert not (q2_aligned + pd.Timedelta(days=30) <= august), \
        f"8月不该看到 Q2 (aligned={q2_aligned.date()})"

    # 11月 → 应该看到 Q1 和 Q2，不该看到 Q3（Q3 aligned ≈ 12月初 +30d ≈ 12月底）
    november = pd.Timestamp("2025-11-15")
    avail = aligned.index[aligned.index + pd.Timedelta(days=30) <= november]
    assert len(avail) >= 2, f"11月应该看到 Q1+Q2: {avail}"

    print("  PASS test_multi_period_boundary")


def test_empty_handling():
    """空 / None 输入不报错。"""
    assert disclosure_align(None) is None
    assert disclosure_align(pd.DataFrame()) is not None
    print("  PASS test_empty_handling")


if __name__ == "__main__":
    print("disclosure_align 边界测试")
    print("-" * 40)
    test_basic_shift()
    test_no_future_leak()
    test_after_disclosure_ok()
    test_multi_period_boundary()
    test_empty_handling()
    print("-" * 40)
    print("全部通过")
