# -*- coding: utf-8 -*-
"""
Step 2：净值回归升频 —— 从季频模拟组合到周频行业仓位

研报做法：把模拟组合拆成行业子组合，用子组合日收益解释基金净值日收益，
回归系数即"净值隐含仓位"。

本实现提供两种自变量口径：

  index_proxy （默认）
      行业子组合收益 ≈ 申万行业指数收益。
      不需要个股行情，但丢掉了"这只基金在该行业里选的是哪几只股"的信息。
      模拟组合仍然发挥作用：用它给每个行业的 β 设上界（锚定），
      避免回归把仓位甩到基金根本没配的行业上。

  stock_level （可选，需额外抓个股行情）
      行业子组合收益 = 该基金模拟组合中该行业成分股的加权收益。
      最贴近研报原文，误差更小，但抓数成本高。

两种模式都走同一个带约束加权 Lasso 求解器。
"""

import warnings

import numpy as np
import pandas as pd

from .solver import solve_weighted_lasso, exp_decay_weights
from . import taxonomy as tx


# ---------------------------------------------------------------- 数据准备

def nav_to_returns(nav_df, col=None):
    """净值序列 -> 日收益率。

    ⚠⚠⚠ 关键：绝不能直接用东财"累计净值"(nav_cum) 算收益！
    东财累计净值 = 单位净值 + 历史累计分红（简单加总，不复利）。
    对分红多的老基金，累计分红可占净值一半以上，导致累计净值分母被
    放大，日收益波动率被压缩约一半，回归 Σβ 会被系统性腰斩
    （实测 161005：nav_unit β≈0.82，nav_cum β≈0.40）。

    正确的被解释变量优先级：
      1) nav_adj  —— 单位净值在除息日把分红加回后累乘的复权净值（最准）
      2) nav_unit —— 单位净值日收益（除息日会有一个小负跳，但 β 量级正确，
                     不会像 nav_cum 那样系统性腰斩）
    不要把 nav_cum 当被解释变量。
    """
    df = nav_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["date"]).sort_values("date").set_index("date")

    if col is None:
        if "nav_adj" in df.columns and df["nav_adj"].notna().sum() > 10:
            col = "nav_adj"
        elif "nav_unit" in df.columns and df["nav_unit"].notna().sum() > 10:
            col = "nav_unit"
        elif "nav_cum" in df.columns:
            col = "nav_cum"

    if col == "nav_cum":
        warnings.warn(
            "⚠ 正在用 nav_cum(累计净值) 算收益——东财累计净值对分红多的基金会"
            "系统性低估 β，强烈建议改用 nav_adj 或 nav_unit。",
            stacklevel=2)

    if col not in df.columns or df[col].isna().all():
        raise ValueError(f"净值缺少可用列（尝试过 {col}）")

    s = pd.to_numeric(df[col], errors="coerce").dropna()
    ret = s.pct_change().dropna()
    ret.name = "fund_ret"
    return ret, col


def index_to_returns(idx_long):
    """行业指数长表 -> 宽表日收益率 (date × 行业名)"""
    df = idx_long.copy()
    df["date"] = pd.to_datetime(df["date"])
    wide = (df.pivot_table(index="date", columns="industry_name",
                           values="close", aggfunc="last")
              .sort_index())
    return wide.pct_change().dropna(how="all")


# ----------------------------------------------------------------
# stock_level 因子构建（替代行业指数）
# ----------------------------------------------------------------

def build_stock_factors(stock_ret, recipe, stock_info, periods, 
                        anchor_mult=None):
    """用个股收益 + 持仓配方构建行业子组合日收益矩阵。

    这是 stock_level 路径的因子来源——每个行业列不再是宏观经济/行业指数，
    而是该基金在该行业实际持有股票的加权日收益。

    参数
    ----
    stock_ret : DataFrame, date × code，个股 qfq 日收益
    recipe    : DataFrame, [period, code, sw, weight]，simulate 产出
    stock_info: dict, period → {code: sw_industry}
    periods   : list of pd.Timestamp, 所有报告期（按时间排序）
    anchor_mult: 若不为 None，stock_level 下仍设锚定；默认 stock_level
                 不锚定（因 sim 信息已进入 X，再锚定是双重约束）

    季末跳变处理：在每个交易日，使用该日前最后一个报告期的配方。
    跨季度窗口内，配方随日历自然切换——不在窗口内固定起点组合，
    因为这本身就是基金的实际调仓节奏，是信息而非噪声。

    返回
    ----
    factor_ret : DataFrame, date × 申万行业，日收益
    """
    if stock_ret is None or recipe is None or len(recipe) == 0:
        raise ValueError("stock_level 需要个股日收益数据和持仓配方，"
                         "两者均不可为空。")

    # 日期索引
    ret_dates = stock_ret.index.sort_values()
    ret_codes = set(stock_ret.columns)

    # ---- 披露滞后对齐（前视偏差修复）
    # 把每个报告期的配方"可用日"后移 45 个交易日，避免自变量在披露前就使用未来持仓。
    # 复用 disclosure_align，和 index_proxy 路径的约束滞后保持一致。
    shifted = {}
    for p in periods:
        # disclosure_align 接受 DataFrame；这里单期包装后对齐再拆回来
        wrapped = pd.DataFrame({"dummy": [0]}, index=pd.DatetimeIndex([p]))
        aligned_idx = disclosure_align(wrapped, bus_days=45).index
        shifted[p] = aligned_idx[0]

    # 报告期→配方映射（索引用可获取日，而非报告日）
    recipe_by_period = {}
    for p in periods:
        rp = recipe[recipe["period"] == p]
        if len(rp) == 0:
            continue
        avail_date = shifted[p]
        recipe_by_period[avail_date] = {
            row["code"]: (row["sw"], row["weight"])
            for _, row in rp.iterrows()
            if row["code"] in ret_codes
        }

    if not recipe_by_period:
        raise ValueError("配方中没有任何股票在日收益数据中，"
                         "请检查股票代码是否匹配。")

    # 所有出现的行业
    all_sw = sorted(set(
        sw for rp in recipe_by_period.values()
        for sw, _ in rp.values()
    ))

    # 逐日构建因子收益
    factor_rows = []
    recipe_periods = sorted(recipe_by_period.keys())
    if not recipe_periods:
        raise ValueError("配方为空，无法构建因子矩阵。")

    for d in ret_dates:
        # 找到 d 之前（含）最近的报告期配方
        candidates = [p for p in recipe_periods if p <= d]
        if not candidates:
            # d 早于最早报告期，用最早报告期配方（向后投射）
            last_p = recipe_periods[0]
        else:
            last_p = candidates[-1]

        rp = recipe_by_period[last_p]

        row = {"date": d}
        for sw in all_sw:
            stocks_in_sw = {
                code: w for code, (s, w) in rp.items() if s == sw
            }
            if not stocks_in_sw:
                row[sw] = 0.0
                continue

            # 加权平均收益——只对当日有数据的股票归一化
            weighted_ret = 0.0
            active_w = 0.0
            for code, w in stocks_in_sw.items():
                if code not in stock_ret.columns:
                    continue
                val = stock_ret.loc[d, code]
                if pd.notna(val):
                    weighted_ret += w * val
                    active_w += w
            row[sw] = weighted_ret / active_w if active_w > 0 else 0.0

        factor_rows.append(row)

    factor_ret = pd.DataFrame(factor_rows).set_index("date")
    # 补齐所有申万行业
    for sw in all_sw:
        if sw not in factor_ret.columns:
            factor_ret[sw] = 0.0
    factor_ret = factor_ret[all_sw].fillna(0.0)

    return factor_ret


# ---------------------------------------------------------------- 滚动回归

def rolling_positions(
    fund_ret,
    factor_ret,
    sim_mat=None,
    window=120,
    half_life=40,
    alpha=1e-6,
    equity_cap="auto",
    freq="W-FRI",
    anchor_mult=None,
    min_obs=60,
    verbose=True,
):
    """滚动窗口回归，输出周频行业仓位。

    参数
    ----
    fund_ret   : Series, 基金日收益（index=date）
    factor_ret : DataFrame, 行业日收益（index=date, columns=行业名）
    sim_mat    : DataFrame, 季度模拟组合 (period × 行业)，用于设 β 上界
    window     : 回归窗口（交易日）
    half_life  : 时间权重半衰期（交易日），<=0 为等权
    alpha      : L1 惩罚强度
    equity_cap : Σβ 上界
    freq       : 输出频率，默认每周五
    anchor_mult: 若给定（如 2.5），则 β_i ≤ anchor_mult × 模拟组合该行业权重 + 0.03
                 None 表示不锚定（纯净值回归）
    min_obs    : 窗口内最少有效观测

    返回
    ----
    (weights_df, diag_df)
      weights_df : 周频 × 行业 的仓位矩阵
      diag_df    : 每期的 R²、Σβ、收敛情况
    """
    # 对齐
    idx = fund_ret.index.intersection(factor_ret.index)
    y_all = fund_ret.reindex(idx).astype(float)
    X_all = factor_ret.reindex(idx).astype(float)

    # 只保留有数据的行业列
    valid_cols = [c for c in X_all.columns if X_all[c].notna().sum() > len(X_all) * 0.5]
    X_all = X_all[valid_cols].fillna(0.0)
    cols = list(X_all.columns)

    if len(idx) < min_obs:
        raise ValueError(f"可用交易日只有 {len(idx)} 天，不足 {min_obs} 天，无法回归")

    # 披露滞后对齐：把模拟组合索引从报告期平移到"实际可获取日"，
    # 避免约束/锚定用到来 disclosure 的未来信息（前视偏差）。
    sim_disc = disclosure_align(sim_mat) if sim_mat is not None and len(sim_mat) else None

    # 输出时点
    rebal = pd.Series(1, index=idx).resample(freq).last().dropna().index
    rebal = [d for d in rebal if d >= idx[min_obs - 1]]

    rows, diags = [], []
    for d in rebal:
        hist = idx[idx <= d]
        if len(hist) < min_obs:
            continue
        win = hist[-window:]
        y = y_all.reindex(win).values
        X = X_all.reindex(win).values
        if np.isnan(y).any():
            keep = ~np.isnan(y)
            y, X, win = y[keep], X[keep], win[keep]
        if len(y) < min_obs:
            continue

        w = exp_decay_weights(len(y), half_life)

        prior = _latest_sim_row(sim_disc, d) if sim_disc is not None else None

        # Σβ 上界：'auto' 表示从已披露仓位推（+5% 缓冲），比设死一个常数准得多。
        # 设死会让回归顶着上限跑，把权益仓位系统性高估。
        cap_t = equity_cap
        if isinstance(equity_cap, str) and equity_cap == "auto":
            cap_t = min(float(prior.sum()) * 1.05, 0.98) if prior is not None else 0.95

        # 逐行业 β 上界锚定
        cap_vec = None
        if anchor_mult is not None and prior is not None:
            cap_vec = np.array([anchor_mult * float(prior.get(c, 0.0)) + 0.03
                                for c in cols])

        res = _solve_with_caps(X, y, w, alpha, cap_t, cap_vec)

        row = {"date": d}
        row.update({c: float(b) for c, b in zip(cols, res["beta"])})
        rows.append(row)
        diags.append({
            "date": d, "r2": res["r2"], "sum_beta": res["sum_beta"],
            "converged": res["converged"], "n_obs": len(y),
            "n_active": int((res["beta"] > 1e-4).sum()),
        })

    if not rows:
        raise ValueError("没有产出任何回归结果，检查数据区间是否过短")

    W = pd.DataFrame(rows).set_index("date")
    D = pd.DataFrame(diags).set_index("date")

    if verbose:
        print(f"  回归时点 {len(W)} 个：{W.index.min().date()} ~ {W.index.max().date()}")
        print(f"  R² 中位数 {D['r2'].median():.3f} | "
              f"Σβ 中位数 {D['sum_beta'].median():.3f} | "
              f"未收敛 {int((~D['converged']).sum())} 期")
        low = (D["r2"] < 0.6).sum()
        if low:
            print(f"  ⚠ 有 {low} 期 R² < 0.6，这些时点的仓位估计可信度低")

    return W, D


def _solve_with_caps(X, y, w, alpha, equity_cap, cap_vec):
    """带逐行业上界的求解。

    求解器本身只支持 β≥0 与 Σβ≤B。逐行业上界通过变量缩放实现：
    令 β = cap ⊙ γ，则 β_i ≤ cap_i 等价于 γ_i ≤ 1，
    再用一次投影把 γ 截断到 [0,1]，交替几轮即可（cap 通常不紧，收敛很快）。
    """
    if cap_vec is None:
        return solve_weighted_lasso(X, y, w=w, alpha=alpha, max_sum=equity_cap)

    cap_vec = np.maximum(cap_vec, 1e-4)
    res = solve_weighted_lasso(X, y, w=w, alpha=alpha, max_sum=equity_cap)

    for _ in range(6):
        over = res["beta"] > cap_vec + 1e-9
        if not over.any():
            break
        # 把超界的行业列从 X 中按上界固定，剩余部分重解
        fixed = np.where(over, cap_vec, 0.0)
        y_adj = y - X @ fixed
        Xr = X.copy()
        Xr[:, over] = 0.0
        rem_cap = max(equity_cap - fixed.sum(), 0.0)
        r2 = solve_weighted_lasso(Xr, y_adj, w=w, alpha=alpha, max_sum=rem_cap)
        beta = r2["beta"].copy()
        beta[over] = cap_vec[over]
        res = {**r2, "beta": beta, "sum_beta": float(beta.sum())}

    # 重算 R²
    pred = X @ res["beta"] + res.get("intercept", 0.0)
    ww = w / w.sum()
    ss_res = float((ww * (y - pred) ** 2).sum())
    ybar = float((ww * y).sum())
    ss_tot = float((ww * (y - ybar) ** 2).sum())
    res["r2"] = 1.0 - ss_res / ss_tot if ss_tot > 1e-18 else np.nan
    return res


def _latest_sim_row(sim_mat, d):
    """取 d 之前（含）最近一期模拟组合，且必须已披露。

    披露滞后按季报 +20 个工作日保守处理，避免前视偏差。
    """
    avail = sim_mat.index[sim_mat.index + pd.Timedelta(days=30) <= d]
    if len(avail) == 0:
        return None
    return sim_mat.loc[avail[-1]]


def disclosure_align(sim_mat, bus_days=45):
    """把模拟组合的指数从"报告期"平移到"实际可获取日"，消除前视偏差。

    季报/年报通常在报告期结束后 45~60 个交易日内披露。如果直接用报告期
    （如 2026-06-30）作为约束/对账的可获取时点，回归会在披露前就"知道"
    该期持仓，对高换手基金会虚增估计的准确度。

    这里把每一期的索引后移 bus_days 个交易日，使约束只用到"当时已披露"
    的信息。bus_days 默认 45（A 股权益基金披露的保守下限）。
    """
    if sim_mat is None or len(sim_mat) == 0:
        return sim_mat
    new_idx = []
    for d in sim_mat.index:
        # 后移 bus_days 个工作日
        shifted = d
        added = 0
        while added < bus_days:
            shifted = shifted + pd.Timedelta(days=1)
            if shifted.weekday() < 5:  # 0=Mon..4=Fri
                added += 1
        new_idx.append(shifted)
    out = sim_mat.copy()
    out.index = pd.DatetimeIndex(new_idx)
    return out


# ---------------------------------------------------------------- 衍生指标

def detect_shifts(W, top_n=5, lookback=4, noise_window=52):
    """识别披露间隔内的隐性调仓：仓位变动最大的行业。

    重要：周频 β 估计本身有噪声，近 lookback 周的变动很可能只是估计波动，
    不代表真实调仓。这里同时给出每个行业 β 的"周变动标准差"(noise_std)，
    并据此标注变动是否落在噪声带内（|变动| <= 1.5×noise_std 视为不可信）。
    对低换手基金经理，绝大多数"调仓"都会落在噪声带里，必须谨慎引用。
    """
    if len(W) < lookback + 1:
        return pd.DataFrame()
    chg = W.iloc[-1] - W.iloc[-1 - lookback]
    up = chg.nlargest(top_n)
    dn = chg.nsmallest(top_n)

    # 每个行业的周频 β 变动标准差（用最近 noise_window 周的样本）
    nw = min(noise_window, len(W) - 1)
    wk_chg = W.diff().tail(nw)
    noise_std = wk_chg.std().fillna(0.0)

    out = pd.concat([
        pd.DataFrame({"行业": up.index, "变动": up.values, "方向": "加仓"}),
        pd.DataFrame({"行业": dn.index, "变动": dn.values, "方向": "减仓"}),
    ], ignore_index=True)
    out["期末仓位"] = out["行业"].map(W.iloc[-1])
    out["噪声带(1.5σ)"] = out["行业"].map(
        lambda c: round(1.5 * noise_std.get(c, 0.0), 4))
    out["可信度"] = out.apply(
        lambda r: "噪声内(谨慎)" if abs(r["变动"]) <= r["噪声带(1.5σ)"] else "超出噪声",
        axis=1)
    return out


def style_drift(W, sim_mat, tol=0.05):
    """风格漂移预警：当前隐含仓位与最近一期季报模拟组合的偏离。"""
    if sim_mat is None or len(sim_mat) == 0 or len(W) == 0:
        return pd.DataFrame()
    latest_sim = sim_mat.iloc[-1]
    cur = W.iloc[-1]
    cols = sorted(set(cur.index) | set(latest_sim.index))
    a = cur.reindex(cols).fillna(0.0)
    b = latest_sim.reindex(cols).fillna(0.0)
    diff = (a - b)
    out = pd.DataFrame({
        "行业": cols, "隐含仓位": a.values,
        "季报模拟": b.values, "偏离": diff.values,
    })
    out = out[out["偏离"].abs() > tol].sort_values("偏离", key=abs, ascending=False)
    return out.reset_index(drop=True)


def reconcile_with_report(W, sim_mat):
    """对账：在每个季报时点，比较回归仓位与模拟组合的一致性。

    这是唯一免费的强校验 —— 如果这里差得离谱，说明回归跑偏了。
    """
    rows = []
    for p in sim_mat.index:
        near = W.index[(W.index >= p - pd.Timedelta(days=10)) &
                       (W.index <= p + pd.Timedelta(days=10))]
        if len(near) == 0:
            continue
        w = W.loc[near].mean()
        s = sim_mat.loc[p]
        cols = sorted(set(w.index) | set(s.index))
        a = w.reindex(cols).fillna(0.0)
        b = s.reindex(cols).fillna(0.0)
        rows.append({
            "报告期": p.date(),
            "回归权益仓位": float(a.sum()),
            "模拟组合仓位": float(b.sum()),
            "行业MAE": float((a - b).abs().mean()),
            "相关系数": float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else np.nan,
        })
    return pd.DataFrame(rows)
