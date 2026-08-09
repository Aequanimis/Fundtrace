# -*- coding: utf-8 -*-
"""
端到端自测：造一只"真实仓位已知"的合成基金，跑完整链路，看能不能还原。

这是唯一能在没有真实数据时验证代码正确性的办法。
它验证的是**代码逻辑**，不是**方法在真实市场上的精度** —— 后者必须等真数据。

造数逻辑：
  31 个申万行业，每行业 20 只股票
  股票日收益 = 行业收益 + 个股特异收益
  基金持有若干股票，行业权重随时间缓慢漂移（模拟真实调仓）
  基金净值 = 持仓加权收益 + 微小噪声
  季报只暴露前十大 + 证监会门类配置，年报暴露全部持股
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import taxonomy as tx
from lib.simulate import SimulatedPortfolio, validate_against_real
from lib.regress import (nav_to_returns, index_to_returns, rolling_positions,
                         reconcile_with_report, detect_shifts)

RNG = np.random.default_rng(7)
INDUSTRIES = sorted(tx.SW_L1.values())


# ---------------------------------------------------------------- 造数

def make_market(n_days=750, n_stock_per_ind=20):
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    ind_ret = pd.DataFrame(
        RNG.normal(0.0003, 0.014, size=(n_days, len(INDUSTRIES))),
        index=dates, columns=INDUSTRIES)

    stocks, srets = {}, {}
    for k, ind in enumerate(INDUSTRIES):
        for j in range(n_stock_per_ind):
            code = f"{(k * 100 + j + 1):06d}"
            stocks[code] = ind
            srets[code] = ind_ret[ind].values + RNG.normal(0, 0.012, n_days)
    stock_ret = pd.DataFrame(srets, index=dates)
    return dates, ind_ret, stock_ret, stocks


def make_fund(dates, ind_ret, stock_ret, stock2ind,
              n_active=8, n_hold_per_ind=6, equity=0.88):
    """造一只行业权重缓慢漂移的基金。"""
    active = list(RNG.choice(INDUSTRIES, size=n_active, replace=False))

    # 两组目标权重，线性插值形成漂移
    w0 = RNG.uniform(0.04, 0.22, n_active); w0 = w0 / w0.sum() * equity
    w1 = RNG.uniform(0.04, 0.22, n_active); w1 = w1 / w1.sum() * equity
    T = len(dates)
    ramp = np.linspace(0, 1, T)[:, None]
    W_true = pd.DataFrame(w0 * (1 - ramp) + w1 * ramp, index=dates, columns=active)

    # 每个活跃行业里挑几只股票，组内固定权重
    picks = {}
    for ind in active:
        pool = [c for c, i in stock2ind.items() if i == ind]
        chosen = list(RNG.choice(pool, size=n_hold_per_ind, replace=False))
        ww = RNG.uniform(0.5, 1.5, n_hold_per_ind); ww = ww / ww.sum()
        picks[ind] = dict(zip(chosen, ww))

    # 个股权重时间序列
    stock_w = pd.DataFrame(0.0, index=dates, columns=sorted(stock2ind))
    for ind in active:
        for c, share in picks[ind].items():
            stock_w[c] = W_true[ind].values * share

    # 基金日收益（用前一日权重，避免同日互指）
    fr = (stock_w.shift(1).fillna(0.0) * stock_ret).sum(axis=1)
    fr += RNG.normal(0, 0.0008, T)          # 交易摩擦/现金拖累
    nav = pd.DataFrame({"date": dates, "nav_cum": (1 + fr).cumprod()})
    return W_true, stock_w, nav, active


def make_reports(dates, stock_w, stock2ind):
    """从真实持仓造出季报（前十大）和年报（全部持股）。"""
    period_ends = [d for d in pd.date_range(dates[0], dates[-1], freq="QE")
                   if d >= dates[0] and d <= dates[-1]]
    hold_rows, alloc_rows, real_rows = [], [], []

    for p in period_ends:
        near = dates[dates <= p]
        if len(near) == 0:
            continue
        snap = stock_w.loc[near[-1]]
        snap = snap[snap > 1e-6].sort_values(ascending=False)
        is_annual = p.month in (6, 12)          # 半年报/年报 -> 全部持股

        # 季报口径：前十大
        for c, w in snap.head(10).items():
            hold_rows.append({"股票代码": c, "股票名称": f"股票{c}",
                              "占净值比例": round(w * 100, 4),
                              "季度": p.strftime("%Y-%m-%d")})
        # 年报口径：全部持股（另存，用于校验；也并入 holdings 模拟真实可得情形）
        if is_annual:
            for c, w in snap.items():
                real_rows.append({"code": c, "pct": w, "period": p})

        # 证监会门类配置
        by_letter = {}
        for c, w in snap.items():
            sw = stock2ind[c]
            for letter, members in tx.CSRC_TO_SW.items():
                if sw in members:
                    by_letter[letter] = by_letter.get(letter, 0.0) + w
                    break
        names = {"A": "A农、林、牧、渔业", "B": "B采矿业", "C": "C制造业",
                 "D": "D电力、热力、燃气及水生产和供应业", "E": "E建筑业",
                 "F": "F批发和零售业", "G": "G交通运输、仓储和邮政业",
                 "H": "H住宿和餐饮业", "I": "I信息传输、软件和信息技术服务业",
                 "J": "J金融业", "K": "K房地产业", "L": "L租赁和商务服务业",
                 "M": "M科学研究和技术服务业", "N": "N水利、环境和公共设施管理业",
                 "O": "O居民服务、修理和其他服务业", "P": "P教育",
                 "Q": "Q卫生和社会工作", "R": "R文化、体育和娱乐业", "S": "S综合"}
        for letter, w in by_letter.items():
            alloc_rows.append({"行业类别": names.get(letter, letter),
                               "占净值比例": round(w * 100, 4),
                               "截止时间": p.strftime("%Y-%m-%d")})

    return (pd.DataFrame(hold_rows), pd.DataFrame(alloc_rows),
            pd.DataFrame(real_rows))


# ---------------------------------------------------------------- 主测试

def main():
    print("=" * 68)
    print("端到端自测（合成数据）")
    print("=" * 68)

    dates, ind_ret, stock_ret, stock2ind = make_market()
    W_true, stock_w, nav, active = make_fund(dates, ind_ret, stock_ret, stock2ind)
    holdings, alloc, real_hold = make_reports(dates, stock_w, stock2ind)

    print(f"\n造数完成：{len(dates)} 个交易日，真实活跃行业 {len(active)} 个")
    print(f"  季报 {holdings['季度'].nunique()} 期 / 行业配置 {alloc['截止时间'].nunique()} 期"
          f" / 年报全持股 {real_hold['period'].nunique()} 期")

    # ---------- Step 1
    print("\n" + "-" * 68)
    print("Step 1  季度模拟组合")
    print("-" * 68)
    sp = SimulatedPortfolio(holdings, alloc, stock2ind, verbose=True)
    sim_mat, info = sp.build_all()
    assert not sim_mat.empty, "模拟组合为空"
    print(f"  产出 {len(sim_mat)} 期 × {sim_mat.shape[1]} 行业")
    print(f"  各期权益仓位合计：{sim_mat.sum(axis=1).round(3).tolist()}")

    # 约束覆盖度诊断
    cons = [i["constraint"] for i in info.to_dict("records") if isinstance(i.get("constraint"), dict)]
    if cons:
        ms = np.mean([c["manufacturing_share"] for c in cons])
        hs = np.mean([c["hard_share"] for c in cons])
        print(f"  约束诊断：制造业占比 {ms:.1%} | 硬约束占比 {hs:.1%}")

    # 还原误差（对年报真实全持股）
    overall, per_ind, manu = validate_against_real(sim_mat, real_hold, stock2ind)
    if overall is not None:
        print(f"  还原 MAE：全行业 {overall:.4%} | 制造业组 {manu:.4%}")
        print(f"  误差最大的 3 个行业：")
        for k, v in per_ind.head(3).items():
            print(f"      {k}  {v:.4%}")
    assert overall is None or overall < 0.05, f"模拟组合误差异常大: {overall}"

    # ---------- Step 2
    print("\n" + "-" * 68)
    print("Step 2  滚动回归升频")
    print("-" * 68)
    fr, _ = nav_to_returns(nav)
    W, D = rolling_positions(fr, ind_ret, sim_mat=sim_mat,
                             window=120, half_life=40, alpha=1e-7,
                             equity_cap="auto", anchor_mult=None, verbose=True)

    # 与真实仓位对比
    common = W.index.intersection(W_true.index)
    a = W.reindex(common).reindex(columns=INDUSTRIES).fillna(0.0)
    b = W_true.reindex(common).reindex(columns=INDUSTRIES).fillna(0.0)
    mae = float((a - b).abs().values.mean())
    # 活跃行业识别准确率
    top_true = set(b.iloc[-1].nlargest(8).index)
    top_est = set(a.iloc[-1].nlargest(8).index)
    hit = len(top_true & top_est)

    print(f"\n  回归 vs 真实仓位：")
    print(f"      全行业 MAE  {mae:.4%}")
    print(f"      前 8 大行业命中 {hit}/8")
    print(f"      权益仓位 估计 {a.iloc[-1].sum():.3f} vs 真实 {b.iloc[-1].sum():.3f}")

    assert mae < 0.02, f"回归还原误差过大: {mae:.4%}"
    assert hit >= 5, f"主要行业识别太差: {hit}/8"

    # ---------- 衍生指标
    print("\n" + "-" * 68)
    print("Step 3  衍生输出")
    print("-" * 68)
    rec = reconcile_with_report(W, sim_mat)
    if len(rec):
        print("  与季报对账（抽 3 期）：")
        print(rec.head(3).to_string(index=False))

    shifts = detect_shifts(W, top_n=3, lookback=4)
    if len(shifts):
        print("\n  近 4 周隐性调仓 Top3：")
        print(shifts.to_string(index=False))

    print("\n" + "=" * 68)
    print("端到端通过：Step1 -> Step2 -> 衍生输出 全链路跑通")
    print("=" * 68)
    print("\n注意：这只验证了代码逻辑正确，不代表方法在真实市场上的精度。")
    print("      真实精度必须等你的实际数据到位后，用年报做样本外检验。")


if __name__ == "__main__":
    main()
