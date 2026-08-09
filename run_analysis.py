#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主入口：单只基金的高频仓位分析

用法：
    python run_analysis.py 001234                  # 用默认参数
    python run_analysis.py 001234 --calibrate      # 高级 Phase A 标定（最长 5 分钟）
    python run_analysis.py 001234 --window 120 --half-life 40 --alpha 1e-6

前置：
    python fetch_data.py base
    python fetch_data.py fund 001234

产出（写到 output/<code>/）：
    weekly_positions.csv    周频行业仓位矩阵
    diagnostics.csv         每期 R² / Σβ / 收敛情况
    sim_portfolio.csv       季度模拟组合
    report.md               分析报告
    positions.png           仓位曲线图
"""

import argparse
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from lib import taxonomy as tx
from lib.simulate import (SimulatedPortfolio, validate_against_real,
                          validate_holdout, normalize_period, parse_pct, pick_col)
from lib.regress import (nav_to_returns, index_to_returns, rolling_positions,
                         reconcile_with_report, detect_shifts, style_drift,
                         disclosure_align, build_stock_factors)


# ---------------------------------------------------------------- 载入

def load_base():
    bdir = os.path.join(ROOT, "base")
    need = {"sw_industry_index.csv": "行业指数日线",
            "stock_industry_map.csv": "个股行业映射"}
    missing = [f"{f}（{d}）" for f, d in need.items()
               if not os.path.exists(os.path.join(bdir, f))]
    if missing:
        sys.exit("底座数据缺失：\n  " + "\n  ".join(missing) +
                 "\n请先运行：python fetch_data.py base")

    idx = pd.read_csv(os.path.join(bdir, "sw_industry_index.csv"))
    smap_raw = pd.read_csv(os.path.join(bdir, "stock_industry_map.csv"), dtype=str)
    stock2sw = _build_stock_map(smap_raw)
    return idx, stock2sw


def _build_stock_map(df):
    """从各种可能的列名结构里抽出 股票代码 -> 申万一级行业。"""
    cols = list(df.columns)
    code_col = next((c for c in cols if "股票代码" in c or "证券代码" in c
                     or c.strip() in ("代码", "code", "stock_code")), None)
    ind_col = next((c for c in cols if "industry_name" == c), None)
    if ind_col is None:
        ind_col = next((c for c in cols if ("行业" in c and "名称" in c)
                        or c.strip() in ("一级行业", "新版一级行业", "行业名称")), None)
    if code_col is None or ind_col is None:
        sys.exit(f"个股行业映射表列名无法识别：{cols}\n"
                 f"需要包含 [股票代码] 和 [行业名称] 两列")

    d = df[[code_col, ind_col]].dropna()
    d.columns = ["code", "sw"]
    d["code"] = d["code"].astype(str).str.extract(r"(\d{6})")[0]
    d["sw"] = d["sw"].astype(str).str.strip()
    # 只保留申万一级
    valid = set(tx.SW_L1.values())
    d = d[d["sw"].isin(valid)].dropna(subset=["code"])
    return dict(zip(d["code"], d["sw"]))


def load_fund(code):
    fdir = os.path.join(ROOT, "funds", code)
    if not os.path.isdir(fdir):
        sys.exit(f"找不到 {fdir}\n请先运行：python fetch_data.py fund {code}")

    def rd(name, required=True):
        p = os.path.join(fdir, name)
        if not os.path.exists(p):
            if required:
                sys.exit(f"缺少 {name}\n请重新运行：python fetch_data.py fund {code}")
            return None
        return pd.read_csv(p, dtype=str)

    nav = rd("nav.csv")
    hold = rd("holdings.csv")
    alloc = rd("industry_alloc.csv", required=False)
    for c in ["nav_unit", "nav_cum"]:
        if c in nav.columns:
            nav[c] = pd.to_numeric(nav[c], errors="coerce")
    return nav, hold, alloc


def extract_real_holdings(hold_df, sp):
    """从持股表里抽出"全部持股"的报告期，用于校验和标定。"""
    if sp.mode != "FULL":
        return pd.DataFrame(columns=["code", "pct", "period"])
    h = sp.hold
    return h[h["period"].isin(sp.full_periods)][["code", "pct", "period"]].copy()


# ---------------------------------------------------------------- 输出

def plot_positions(W, outpath, top_n=8):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return False

    # 中文字体：找不到就用英文行业代码，不让图糊掉
    zh = None
    for cand in ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei",
                 "Microsoft YaHei", "PingFang SC", "Source Han Sans CN"]:
        try:
            font_manager.findfont(cand, fallback_to_default=False)
            zh = cand
            break
        except Exception:
            continue
    if zh:
        matplotlib.rcParams["font.sans-serif"] = [zh]
        matplotlib.rcParams["axes.unicode_minus"] = False

    top = W.iloc[-1].nlargest(top_n).index.tolist()
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for c in top:
        label = c if zh else tx.SW_NAME_TO_CODE.get(c, c)
        ax.plot(W.index, W[c] * 100, linewidth=1.7, label=label)
    ax.set_ylabel("Position (%)" if not zh else "仓位 (%)")
    ax.set_title("Weekly implied industry positions" if not zh
                 else "周频隐含行业仓位（前 %d 大）" % top_n)
    ax.legend(ncol=2, fontsize=9)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)
    return True


def write_report(path, code, sp, sim_mat, info, W, D, mae_info,
                 rec, shifts, drift, params, chart_ok, nav_col="nav_adj",
                 cv_mae=None, factor_source="index_proxy"):
    L = []
    a = L.append
    a(f"# 基金 {code} 高频行业仓位分析\n")
    a(f"生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}\n")

    # ---- 可信度先说
    a("## 0. 先看这里：这份结果有多可信\n")

    # ---- 可信度评级（A/B/C/D）----
    r2_med = float(D["r2"].median())
    mae_val = mae_info[0] if mae_info and mae_info[0] is not None else None
    grade_score = 4
    if sp.mode == "TOP10_ONLY": grade_score -= 1
    if sp.mode == "EMPTY":       grade_score -= 2
    if r2_med < 0.85:           grade_score -= 1
    if r2_med < 0.60:           grade_score -= 2
    if mae_val is not None and mae_val > 0.02: grade_score -= 1
    if mae_val is not None and mae_val > 0.03: grade_score -= 1
    grade_map = {4: "A - 可信", 3: "B - 基本可信，局部谨慎",
                 2: "C - 谨慎使用，多交叉验证",
                 1: "D - 严重受限，仅作参考",
                 0: "D - 严重受限，仅作参考",
                 -1: "D - 严重受限，仅作参考"}
    grade = grade_map.get(max(grade_score, -1), "D")
    a(f"**可信度评级：{grade}**")
    a("")
    # ----
    mode_txt = {"FULL": "FULL（能拿到全部持股，走完整递归）",
                "TOP10_ONLY": "TOP10_ONLY（只有前十大，非重仓靠外推）",
                "EMPTY": "EMPTY（无持股数据）"}[sp.mode]
    a(f"- **运行模式**：{mode_txt}")
    if sp.mode != "FULL":
        a("- ⚠ **只有前十大重仓股**，非重仓部分完全靠上期结构外推，"
          "误差会明显放大。建议补传年报/半年报的全部持股。")
        a("  - 因此下方「各行业仓位之和」会明显小于上面的 Σβ："
          "非重仓股未纳入行业映射，看总权益暴露请直接用 Σβ。")

    cons = [i["constraint"] for i in info.to_dict("records")
            if isinstance(i.get("constraint"), dict)]
    if cons:
        ms = float(np.mean([c["manufacturing_share"] for c in cons]))
        hs = float(np.mean([c["hard_share"] for c in cons]))
        a(f"- **约束强度**：制造业占权益 {ms:.1%}，真正的硬约束（一对一映射）仅 {hs:.1%}")
        a(f"  - 季报的行业约束在证监会门类层，制造业是一整行。"
          f"这 {ms:.1%} 的仓位在电子/电新/医药/机械之间怎么分，"
          f"**季报没有约束力，全靠持仓惯性假设**。这部分结论要打折看。")

    if mae_info and mae_info[0] is not None:
        overall, per_ind, manu = mae_info
        a(f"- **模拟组合还原误差（留一法）**：全行业 MAE {overall:.3%}"
          f"（研报基准 0.6%），制造业组 {manu:.3%}")
        verdict = "达标" if overall < 0.01 else ("偏高，结论谨慎" if overall < 0.02 else "过大，不建议采信")
        a(f"  - 判定：**{verdict}**")
        a("  - 口径说明：把每个年报期**当作只有前十大**重建后再与真实值比。"
          "直接拿年报期比对等于拿答案对答案，MAE 恒为 0，那个数没有意义。")
        if per_ind is not None and len(per_ind):
            worst = ", ".join(f"{k} {v:.2%}" for k, v in per_ind.head(3).items())
            a(f"  - 误差最大的行业：{worst}")
    else:
        a("- ⚠ **无法计算还原误差**（没有真实全持股作为基准），"
          "本次结果未经任何客观校验，请谨慎使用。")

    a(f"- **回归拟合**：R² 中位数 {D['r2'].median():.3f}，"
      f"低于 0.6 的时点 {int((D['r2'] < 0.6).sum())}/{len(D)} 个")
    if (D["r2"] < 0.6).mean() > 0.2:
        a("  - ⚠ 超过两成时点拟合很差，说明模拟组合覆盖不了该基金主要收益来源"
          "（可能持仓集中在个别股票、或大量投港股/衍生品），存在误归因风险。")
    sb = float(D["sum_beta"].median())
    a(f"- **Σβ 中位数 {sb:.1%}**（权益仓位估计量级）。"
      f"净值列={nav_col}。")
    if sb < 0.5 and sp.mode == "FULL":
        a("  - ⚠ Σβ 中位数异常偏低。若基金是偏股型，先确认净值口径："
          "用东财累计净值(nav_cum)算收益会把 Σβ 系统性腰斩，"
          "必须改用 nav_adj / nav_unit（复权净值）。")
    if cv_mae is not None:
        a(f"- **标定误差（CV）**：{cv_mae:.3%}（时间序列交叉验证，未见过的测试期 MAE）")
        a("  - 这是一个诚实的、没被数据泄漏污染的误差估计。")
    elif params.get("source", "").startswith("保守默认"):
        a("- **标定**：真实持仓不足，采用保守默认参数（未做参数优化），结论可靠但可能偏保守。")
    a("")

    # ---- 参数
    a("## 1. 参数\n")
    a("| 参数 | 取值 | 说明 |")
    a("|---|---|---|")
    a(f"| 回归窗口 | {params['window']} 个交易日 | 研报未披露，本次取值见下 |")
    a(f"| 时间权重半衰期 | {params['half_life']} 天 | 0 表示等权 |")
    a(f"| Lasso 强度 alpha | {params['alpha']:.1e} | |")
    a(f"| 逐行业锚定倍数 | {params['anchor_mult']} | None 表示纯净值回归 |")
    a(f"| Σβ 上界 | 自动（按已披露仓位 ×1.05） | |")
    a(f"| 标定方式 | {params.get('source', '默认值')} | |")
    mode_label = {"index_proxy": "申万行业指数", 
                  "stock_level": "个股行情穿透（子组合因子）"}
    a(f"| 因子来源 | {mode_label.get(factor_source, factor_source)} | |")
    if factor_source == "stock_level":
        a(f"| 锚定上界 | 已禁用（stock_level 下 sim 信息已入 X，双重约束会削弱调仓探测） | |")
    a("")
    a("> 研报把这些参数全部隐去了，所以**这不是复刻，是重建**。"
      "数字对不上原文是必然的。\n")

    # ---- 当前仓位
    a("## 2. 最新一期隐含行业仓位\n")
    cur = W.iloc[-1].sort_values(ascending=False)
    cur = cur[cur > 0.005]
    a(f"截至 {W.index[-1]:%Y-%m-%d}，权益仓位合计 **{W.iloc[-1].sum():.1%}**\n")
    a("| 行业 | 仓位 |")
    a("|---|---|")
    for k, v in cur.head(15).items():
        a(f"| {k} | {v:.2%} |")
    a("")

    # ---- 隐性调仓
    if len(shifts):
        a("## 3. 披露间隔内的隐性调仓（近 4 周）\n")
        a("这是整套方法最容易被误读的部分：**周频 β 估计本身有噪声**，"
          "近 4 周的变动很可能只是估计波动，不是真实调仓。\n")
        a("| 行业 | 方向 | 变动 | 期末仓位 | 噪声带(1.5σ) | 可信度 |")
        a("|---|---|---|---|---|---|")
        for _, r in shifts.iterrows():
            nb = r["噪声带(1.5σ)"] if "噪声带(1.5σ)" in r else float("nan")
            cred = r["可信度"] if "可信度" in r else ""
            a(f"| {r['行业']} | {r['方向']} | {r['变动']:+.2%} | "
              f"{r['期末仓位']:.2%} | {nb:.2%} | {cred} |")
        a("")
        a("> 凡落在「噪声带」内的行业，其变动极可能是估计噪声——对低换手基金经理"
          "尤其如此，引用前请先等下一期季报验证。\n")
        a("")

    # ---- 漂移
    if len(drift):
        a("## 4. 相对最近季报的偏离（风格漂移预警）\n")
        a("| 行业 | 隐含仓位 | 季报模拟 | 偏离 |")
        a("|---|---|---|---|")
        for _, r in drift.head(10).iterrows():
            a(f"| {r['行业']} | {r['隐含仓位']:.2%} | {r['季报模拟']:.2%} | {r['偏离']:+.2%} |")
        a("")
        a("> 偏离大不等于基金真的漂了 —— 也可能是回归误归因。"
          "建议结合 R² 和下一期季报交叉验证。\n")

    # ---- 对账
    if len(rec):
        a("## 5. 与季报对账\n")
        a("唯一免费的强校验：在季报时点，回归结果应该和模拟组合对得上。\n")
        a("| 报告期 | 回归仓位 | 模拟组合 | 行业MAE | 相关系数 |")
        a("|---|---|---|---|---|")
        for _, r in rec.tail(8).iterrows():
            a(f"| {r['报告期']} | {r['回归权益仓位']:.1%} | {r['模拟组合仓位']:.1%} | "
              f"{r['行业MAE']:.2%} | {r['相关系数']:.3f} |")
        a("")
        bad = rec[rec["相关系数"] < 0.5]
        if len(bad):
            a(f"> ⚠ 有 {len(bad)} 期相关系数低于 0.5，这些时点回归跑偏了，别用。\n")

    if chart_ok:
        a("## 6. 仓位曲线\n")
        a("![仓位曲线](positions.png)\n")

    a("---\n")
    a("## 方法与局限\n")
    a("- 本结果是**收益口径暴露**，不是真实持仓还原。持仓集中、"
      "个股特异性强或频繁做波段的基金，模型会把无法解释的收益甩给相关性最高的行业。")
    a("- 行业口径为申万一级（研报主口径为中信，需 Wind 授权；研报也测过申万，结论一致）。")
    a("- 行业子组合收益用行业指数代理，未穿透到该基金实际持股，"
      "这会损失『基金在行业内选股偏离』的信息。")
    a("- 所有季报数据按披露滞后（报告期 +30 天）对齐，避免前视偏差。")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ---------------------------------------------------------------- 主流程

def main():
    run_started = time.monotonic()
    ap = argparse.ArgumentParser(description="基金高频行业仓位分析")
    ap.add_argument("code", help="6 位基金代码")
    ap.add_argument("--calibrate", action="store_true",
                    help="用年报真实持仓标定参数（推荐，慢几分钟）")
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--half-life", type=int, default=40)
    ap.add_argument("--alpha", type=float, default=1e-6)
    ap.add_argument("--anchor-mult", type=float, default=None)
    ap.add_argument("--stock-level", action="store_true",
                    help="用个股行情构建行业子组合因子（stock_level 路径），"
                         "替代默认的申万行业指数。需要预先生成 stock_klines.csv。"
                         "仅在 FULL 模式下可用，TOP10_ONLY 强制 index_proxy。"
                         "stock_level 下默认不设 anchor 上界。")
    ap.add_argument("--calibration-timeout-seconds", type=float, default=None,
                    help="标定 worker 硬超时；生产默认 300 秒，仅用于测试覆盖")
    args = ap.parse_args()

    code = args.code.zfill(6)
    print("=" * 68)
    print(f"基金 {code} 高频行业仓位分析")
    print("=" * 68)

    print("\n[1/5] 载入数据")
    idx_long, stock2sw = load_base()
    nav, hold, alloc = load_fund(code)
    print(f"  行业指数 {idx_long['industry_name'].nunique()} 个 | "
          f"个股映射 {len(stock2sw)} 只 | 净值 {len(nav)} 行 | 持股 {len(hold)} 行")

    print("\n[2/5] Step 1  季度模拟组合")
    sp = SimulatedPortfolio(hold, alloc, stock2sw, verbose=True)
    sim_mat, info = sp.build_all()
    if sim_mat.empty:
        sys.exit("模拟组合构建失败，检查持股数据")
    print(f"  产出 {len(sim_mat)} 期")

    # ---- stock_level 配方
    stock_recipe = None
    stock_info = None
    stock_periods = sorted(sp.hold["period"].unique())
    stock_factor_source = "index_proxy"

    if args.stock_level:
        if sp.mode != "FULL":
            sys.exit("stock_level 路径仅支持 FULL 模式。"
                     "TOP10_ONLY 下非重仓个股不可靠，穿透无意义。")
        print("\n[stock_level] 构建个股配方")
        stock_recipe, stock_info = sp.build_stock_recipe()
        if stock_recipe.empty:
            sys.exit("个股配方构建失败。")
        print(f"  配方 {len(stock_recipe)} 行，"
              f"{stock_recipe['code'].nunique()} 只个股，"
              f"{stock_recipe['period'].nunique()} 个报告期")

    real_hold = extract_real_holdings(hold, sp)
    # 留一法校验：把每个年报期当作只有前十大重建，再与真实值比。
    # 直接拿年报期比对等于拿答案对答案，MAE 会恒等于 0，那个数字是假的。
    overall, per_ind, manu, detail = validate_holdout(sp)
    mae_info = (overall, per_ind, manu)
    if overall is not None:
        print(f"  留一校验 MAE：全行业 {overall:.3%} | 制造业组 {manu:.3%} "
              f"（{len(detail)} 个真实时点）")
    elif len(real_hold) == 0:
        print("  ⚠ 无真实全持股，无法校验还原误差")

    print("\n[3/5] 准备回归输入")
    fund_ret, nav_col = nav_to_returns(nav)
    factor_ret = index_to_returns(idx_long)
    print(f"  基金收益 {len(fund_ret)} 天（净值列={nav_col}）| 行业收益 {factor_ret.shape}")

    # ---- stock_level: 用个股行情替换行业指数
    if args.stock_level:
        kline_path = os.path.join(ROOT, "base", "stock_klines.csv")
        if not os.path.exists(kline_path):
            sys.exit(f"缺少全局个股 K 线缓存：{kline_path}\n"
                     "请先运行：python fetch_stock_klines.py <代码>")
        print(f"  [stock_level] 加载个股 K 线")
        stock_klines = pd.read_csv(kline_path, dtype={"date": str, "code": str, "close": float})
        stock_klines["date"] = pd.to_datetime(stock_klines["date"])
        # 长表 date × code × close → 宽表 date × code（收益率）
        stock_ret_wide = (
            stock_klines.pivot_table(index="date", columns="code",
                                     values="close", aggfunc="last")
            .sort_index().pct_change().dropna(how="all")
        )
        print(f"    个股收益矩阵 {stock_ret_wide.shape}")

        print(f"  [stock_level] 构建行业子组合因子")
        factor_ret = build_stock_factors(
            stock_ret_wide, stock_recipe, stock_info, stock_periods,
        )
        print(f"    因子矩阵 {factor_ret.shape}，行业 {factor_ret.shape[1]} 个")
        stock_factor_source = "stock_level"

        # stock_level 下强制不锚定 —— sim 信息已在 X 中，重复约束会
        # 把回归过度压向季报持仓，削弱探测空窗期偏离的能力。
        # 不再只是 print，而是真的把参数置 None（审计修复：self-contradiction）。
        args.anchor_mult = None
        print("  [stock_level] 已强制禁用 anchor 上界（避免双重约束）")

    params = {"window": args.window, "half_life": args.half_life,
              "alpha": args.alpha, "anchor_mult": args.anchor_mult,
              "source": "命令行/默认值"}

    cv_mae = None  # 交叉验证 MAE 初始为空

    if args.calibrate:
        if not len(real_hold):
            print("  ⚠ 没有真实全持股，无法标定，改用默认参数")
        else:
            print("\n[3.5/5] Phase A 参数标定（独立 worker，最长 5 分钟）")
            from lib.calibration_watchdog import run_calibration_watchdog
            calibration = run_calibration_watchdog(
                code,
                ROOT,
                stock_level=args.stock_level,
                timeout_seconds=args.calibration_timeout_seconds,
            )
            status = calibration["status"]
            print(f"  标定状态：{status} | 完成 "
                  f"{calibration['completed_combos']}/{calibration['total_combos']} | "
                  f"耗时 {calibration['elapsed_seconds']:.2f}s")
            if status == "COMPLETED":
                print("  Phase A candidate 已保存，但不会用于本次正式分析。")
            elif status in ("TIMEOUT_SAFE_STOP", "TIMEOUT_HARD_KILL"):
                print("  未完成结果不会用于正式分析；本次继续使用命令行/稳健默认参数。")
            else:
                print("  ⚠ 标定 worker 未成功完成；本次继续使用命令行/稳健默认参数。")

    print("\n[4/5] Step 2  滚动回归升频")
    W, D = rolling_positions(fund_ret, factor_ret, sim_mat=sim_mat,
                             window=params["window"], half_life=params["half_life"],
                             alpha=params["alpha"], equity_cap="auto",
                             anchor_mult=params["anchor_mult"], verbose=True)

    print("\n[5/5] 输出")
    outdir = os.path.join(ROOT, "output", code)
    os.makedirs(outdir, exist_ok=True)

    W.to_csv(os.path.join(outdir, "weekly_positions.csv"), encoding="utf-8-sig")
    D.to_csv(os.path.join(outdir, "diagnostics.csv"), encoding="utf-8-sig")
    sim_mat.to_csv(os.path.join(outdir, "sim_portfolio.csv"), encoding="utf-8-sig")

    rec = reconcile_with_report(W, sim_mat)
    shifts = detect_shifts(W, top_n=5, lookback=4)
    # 漂移对比只用"已披露"的最近一期，避免拿未披露的季报当期持仓当基准
    sim_disc = disclosure_align(sim_mat)
    drift = style_drift(W, sim_disc, tol=0.03)
    chart_ok = plot_positions(W, os.path.join(outdir, "positions.png"))

    write_report(os.path.join(outdir, "report.md"), code, sp, sim_mat, info,
                 W, D, mae_info, rec, shifts, drift, params, chart_ok, nav_col,
                 cv_mae=cv_mae, factor_source=stock_factor_source)

    print(f"  已写入 output/{code}/")
    for f in ["report.md", "weekly_positions.csv", "sim_portfolio.csv",
              "diagnostics.csv"] + (["positions.png"] if chart_ok else []):
        print(f"      {f}")
    print("\n完成。先看 report.md 第 0 节判断这份结果能不能用。")
    total_elapsed = time.monotonic() - run_started
    if not args.calibrate and total_elapsed > 120:
        with open(os.path.join(outdir, "fast_analysis_timeout.log"), "w", encoding="utf-8") as f:
            f.write(f"fast analysis elapsed_seconds={total_elapsed:.3f}\n")


if __name__ == "__main__":
    main()
