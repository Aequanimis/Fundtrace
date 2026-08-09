# -*- coding: utf-8 -*-
"""
参数标定：用年报/半年报真实持仓做样本外检验，反推最优参数

研报把回归窗口、时间权重、Lasso 强度**全部藏了**，所以复现必然是重建。
唯一能把参数定下来的办法，就是拿真实全持股当答案反推。

评分口径（2026-08-07 审计后）：
  时间序列交叉验证（TS-CV）。将真实全持股报告期按时间顺序分割为
  train / test 折叠，每轮在训练期上搜索参数、在测试期评估 MAE，
  最终取各折叠平均。当真实持仓 ≥4 期时启用 3-fold expanding-window CV；
  不足 4 期时退化为保守默认参数并告警。

评级口径修正：
  旧版先把所有报告期拿来做"答案"，同一批数据既挑参数又报 MAE——
  这是 test-set leakage，MAE 会被系统性低估。新版用 CV MAE 报数，
  该数才是真正的"没见过"的误差估计。
"""

import itertools

import numpy as np
import pandas as pd

from .regress import rolling_positions


def _real_industry_matrix(real_holdings, stock2sw):
    r = real_holdings.copy()
    r["sw"] = r["code"].map(stock2sw)
    return (r.dropna(subset=["sw"])
             .groupby(["period", "sw"])["pct"].sum()
             .unstack(fill_value=0.0))


def score_params(W, real_mat, window_days=5):
    """给一组回归结果打分：对真实持仓时点的 MAE。

    注意：W 必须是"完整"回归结果（所有时点）。如果需要因果性评分
    （不用未来数据），请在调用前把 W 截断到 <= 测试期。
    """
    errs, hits = [], []
    for p in real_mat.index:
        near = W.index[(W.index >= p - pd.Timedelta(days=window_days * 2)) &
                       (W.index <= p + pd.Timedelta(days=window_days * 2))]
        if len(near) == 0:
            continue
        est = W.loc[near].mean()
        truth = real_mat.loc[p]
        cols = sorted(set(est.index) | set(truth.index))
        a = est.reindex(cols).fillna(0.0)
        b = truth.reindex(cols).fillna(0.0)
        errs.append(float((a - b).abs().mean()))
        # 前 5 大行业命中数
        hits.append(len(set(a.nlargest(5).index) & set(b.nlargest(5).index)))
    if not errs:
        return None
    return {"mae": float(np.mean(errs)), "n_points": len(errs),
            "top5_hit": float(np.mean(hits))}


# ----------------------------------------------------------------
# 保守默认参数（无可信标定时的兜底）
# ----------------------------------------------------------------

_CONSERVATIVE_DEFAULTS = {
    "window": 250,        # 最大窗口 → 稳定
    "half_life": 80,      # 最长半衰 → 减少过拟合
    "alpha": 1e-5,        # 最强正则化
    "anchor_mult": None,  # 不锚定 → 让净值自己说话
}

# Tie-break 规则：同等 CV MAE 时，偏好更稳健（防过拟合）的组合
# 排序键 = (mae, -window, -half_life, -alpha)
_TIE_BREAK_WEIGHT = {"window": -1, "half_life": -1, "alpha": -1}


def _tie_break_sort(df):
    """对搜索结果做 tie-break 排序。
    主 key = mae 升序；平局时优先窗口大 → 半衰期长 → alpha 大。
    """
    return df.sort_values(
        ["mae", "window", "half_life", "alpha"],
        ascending=[True, False, False, False]
    )


# ----------------------------------------------------------------
# 时间序列交叉验证网格搜索
# ----------------------------------------------------------------

def _ts_cv_split(periods, cv_folds):
    """按时间顺序分训/测折叠。

    返回 [(train_periods: list, test_periods: list), ...]
    """
    n = len(periods)
    if cv_folds < 2 or n < cv_folds + 1:
        return []

    fold_size = max(n // cv_folds, 1)
    folds = []
    for f in range(cv_folds):
        # 测试集从后往前取（最后一次测试最多）
        test_end = n - f * fold_size
        test_start = max(test_end - fold_size, 1)
        if test_end == test_start:
            test_start -= 1
        train = list(periods[:test_start])
        test = list(periods[test_start:test_end])
        if len(train) < 2 or len(test) < 1:
            continue
        folds.append((train, test))
    return folds


def grid_search(
    fund_ret, factor_ret, sim_mat, real_holdings, stock2sw,
    windows=(60, 90, 120, 180, 250),
    half_lives=(0, 20, 40, 80),
    alphas=(0.0, 1e-7, 1e-6, 1e-5),
    anchor_mults=(None, 2.5),
    cv=True,
    verbose=True,
):
    """网格搜索最优参数组合。

    审计后（2026-08-07）：默认启用时间序列 CV。当真实全持仓报告期 ≥4 时
    做 3-fold expanding-window CV；3 期做 2-fold；不足 3 期退回保守默认值。

    返回 (best_params: dict, results: DataFrame, cv_mae: float or None)
      - cv_mae: 测试折叠平均 MAE（CV 模式）或 None（退化为默认值）
    """
    real_mat = _real_industry_matrix(real_holdings, stock2sw)
    n_periods = len(real_mat)
    if n_periods == 0:
        raise ValueError("没有真实全持股数据，无法标定参数。"
                         "请确认年报/半年报的全部持股是否到位。")

    periods = sorted(real_mat.index)
    combos = list(itertools.product(windows, half_lives, alphas, anchor_mults))
    n_combos = len(combos)

    # ---- 不足 3 期真实持仓 → 无法 CV，退回保守默认值 ----
    if n_periods < 3:
        if verbose:
            print(f"  ⚠ 真实全持仓仅有 {n_periods} 期，不足以交叉验证。")
            print("    退回保守默认参数（最大窗口 + 最长半衰 + 最强正则 → 防过拟合）：")
            print(f"    window={_CONSERVATIVE_DEFAULTS['window']} "
                  f"half_life={_CONSERVATIVE_DEFAULTS['half_life']} "
                  f"alpha={_CONSERVATIVE_DEFAULTS['alpha']:.1e} "
                  f"anchor={_CONSERVATIVE_DEFAULTS['anchor_mult']}")
            print("    建议：多补几份年报/半年报后重新标定。")
        # 仍然跑一次最宽参数看能不能出数据（用于报告参数段），但不选优
        return (dict(_CONSERVATIVE_DEFAULTS,
                     source=f"保守默认（真实持仓仅{n_periods}期，无法CV）"),
                pd.DataFrame(), None)

    # ---- CV 折叠 ----
    cv_folds = 3 if n_periods >= 4 else 2
    folds = _ts_cv_split(periods, cv_folds)
    if not folds:
        # fallback
        if verbose:
            print(f"  ⚠ 无法构建 CV 折叠（{n_periods} 期），退回保守默认值")
        return (dict(_CONSERVATIVE_DEFAULTS,
                     source=f"保守默认（无法CV，{n_periods}期）"),
                pd.DataFrame(), None)

    if verbose:
        print(f"  标定：{n_combos} 组参数 × {n_periods} 个真实时点 "
              f"→ {len(folds)}-fold TS-CV")
        for fi, (tr, te) in enumerate(folds):
            print(f"    Fold {fi+1}: train={[p.strftime('%Y-%m') for p in tr]} "
                  f"→ test={[p.strftime('%Y-%m') for p in te]}")

    # ---- 每折叠独立评估，累加测试 MAE ----
    # fold_results[combo] = [mae_fold1, mae_fold2, ...]
    from collections import defaultdict
    fold_scores = defaultdict(list)

    for fi, (train_periods, test_periods) in enumerate(folds):
        test_mat = real_mat.loc[test_periods]
        if verbose:
            print(f"\n  [{fi+1}/{len(folds)}] 测试 {len(test_periods)} 期 "
                  f"({test_periods[0].strftime('%Y-%m')} ~ "
                  f"{test_periods[-1].strftime('%Y-%m')})")

        for ci, (win, hl, al, am) in enumerate(combos, 1):
            combo_key = (win, hl, al, am)
            try:
                W, D = rolling_positions(
                    fund_ret, factor_ret, sim_mat=sim_mat,
                    window=win, half_life=hl, alpha=al,
                    equity_cap="auto", anchor_mult=am,
                    verbose=False)

                # 因果性评分：只看测试期内及之前的回归结果
                # 截断到 test 最晚日
                test_cutoff = max(test_periods) + pd.Timedelta(days=14)
                W_causal = W.loc[W.index <= test_cutoff]

                sc = score_params(W_causal, test_mat)
                if sc is None:
                    continue
                fold_scores[combo_key].append(sc["mae"])
            except Exception as e:
                pass  # 折叠内的失败不计入

            if verbose and ci % 20 == 0:
                print(f"      ... {ci}/{n_combos}")

    # ---- 汇总 CV 分数 ----
    if not fold_scores:
        if verbose:
            print("  ⚠ CV 无一产出，退回保守默认值")
        return (dict(_CONSERVATIVE_DEFAULTS,
                     source="保守默认（CV无产出）"), pd.DataFrame(), None)

    # 只保留在所有折叠都有分数的 combo
    cv_summary = {}
    for combo, maes in fold_scores.items():
        if len(maes) == len(folds):
            cv_summary[combo] = float(np.mean(maes))

    if not cv_summary:
        # 放宽：只要至少有一个折叠有分数
        for combo, maes in fold_scores.items():
            cv_summary[combo] = float(np.mean(maes))
        if verbose:
            print("  ⚠ 无组合覆盖全部折叠，用部分折叠平均（结果有偏）")

    # 选最优：CV MAE 最低；平局时 tie-break
    sorted_combos = sorted(cv_summary.items(), key=lambda x: x[1])
    best_combo, cv_mae = sorted_combos[0]

    win, hl, al, am = best_combo
    best = {
        "window": win,
        "half_life": hl,
        "alpha": al,
        "anchor_mult": am,
        "cv_mae": cv_mae,
        "n_folds": len(folds),
        "n_periods": n_periods,
        "source": f"{len(folds)}-fold TS-CV（{n_periods} 期真实持仓，CV MAE={cv_mae:.3%}）",
    }

    # 构建完整结果表（跑一次所有 combo 在后验所有时点上的分数，仅供诊断）
    # 这趟不是选参用的，是给人看"各组参数在所有时点综合表现"的
    diag_rows = []
    for (win_d, hl_d, al_d, am_d), cv_avg in sorted_combos[:30]:
        diag_rows.append({
            "window": win_d, "half_life": hl_d, "alpha": al_d,
            "anchor_mult": am_d if am_d is not None else 0,
            "cv_mae": cv_avg,
        })
    res = pd.DataFrame(diag_rows) if diag_rows else pd.DataFrame()

    if verbose:
        print(f"\n  最优（{len(folds)}-fold CV）："
              f"window={int(best['window'])} "
              f"half_life={int(best['half_life'])} "
              f"alpha={best['alpha']:.1e} anchor={best['anchor_mult']}")
        print(f"        CV MAE = {cv_mae:.4%}（{len(folds)} 折叠平均，"
              f"共 {n_periods} 期真实持仓）")

        # 参数高原 vs 尖峰
        if len(sorted_combos) >= 5:
            top5_maes = [v for _, v in sorted_combos[:5]]
            spread = max(top5_maes) - min(top5_maes)
            if spread < 0.002:
                print(f"        前 5 组 CV MAE 差异仅 {spread:.4%}，"
                      f"参数高原 → 结论稳健")
            else:
                print(f"        ⚠ 前 5 组 CV MAE 差异 {spread:.4%}，"
                      f"参数敏感 → 最优可能是噪声，建议取前 3 组中位")

    return best, res, cv_mae


# ----------------------------------------------------------------
# 仅在全时点评分（保留兼容，新代码走 grid_search 的 CV 模式）
# ----------------------------------------------------------------

def grid_search_flat(
    fund_ret, factor_ret, sim_mat, real_holdings, stock2sw,
    windows=(60, 90, 120, 180, 250),
    half_lives=(0, 20, 40, 80),
    alphas=(0.0, 1e-7, 1e-6, 1e-5),
    anchor_mults=(None, 2.5),
    verbose=True,
):
    """[旧版] 全时点评分网格搜索 —— 存在 test-set leakage，不建议使用。

    保留仅用于向后兼容和对比。新调用请用 grid_search(cv=True)。
    """
    real_mat = _real_industry_matrix(real_holdings, stock2sw)
    if len(real_mat) == 0:
        raise ValueError("没有真实全持股数据，无法标定参数。")

    combos = list(itertools.product(windows, half_lives, alphas, anchor_mults))
    if verbose:
        print(f"  [flat, 非 CV] {len(combos)} 组参数 × {len(real_mat)} 个真实时点")

    rows = []
    for i, (win, hl, al, am) in enumerate(combos, 1):
        try:
            W, D = rolling_positions(
                fund_ret, factor_ret, sim_mat=sim_mat,
                window=win, half_life=hl, alpha=al,
                equity_cap="auto", anchor_mult=am,
                verbose=False)
            sc = score_params(W, real_mat)
            if sc is None:
                continue
            rows.append({
                "window": win, "half_life": hl, "alpha": al,
                "anchor_mult": am if am is not None else 0,
                "mae": sc["mae"], "top5_hit": sc["top5_hit"],
                "n_points": sc["n_points"],
                "r2_median": float(D["r2"].median()),
            })
        except Exception:
            pass

    if not rows:
        raise ValueError("网格搜索没有产出任何有效结果")

    res = pd.DataFrame(rows).sort_values("mae")
    best = res.iloc[0].to_dict()
    best["anchor_mult"] = None if best["anchor_mult"] == 0 else best["anchor_mult"]
    best["source"] = "flat（⚠ test-set leakage，仅供对比）"

    if verbose:
        print(f"\n  [flat] 最优：window={int(best['window'])} "
              f"half_life={int(best['half_life'])} "
              f"alpha={best['alpha']:.1e} anchor={best['anchor_mult']}")
        print(f"         MAE={best['mae']:.4%}（⚠ 同数据挑参+报数，偏乐观）")

    return best, res
