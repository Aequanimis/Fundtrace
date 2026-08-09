# -*- coding: utf-8 -*-
"""
Step 1：重仓股行业补全法 —— 构建季度模拟组合

研报原文四步：
  1. 筛选合格样本
  2. 计算非重仓行业缺口  W_nonkey[i] = max(W_fund[i] - W_key[i], 0)
  3. 约束非重仓个股权重（上限 = 当期重仓股最小权重）
  4. 处理港股

本实现的关键调整（研报没说，但绕不过去）：
  季报的行业约束在**证监会门类**层，输出要在**申万一级**层。
  所以第 2 步改成：门类层算缺口 -> 组内按上期持仓结构分配到申万行业。

两种运行模式，自动判定：
  FULL      —— 能拿到年报/半年报全部持股，走完整递归。误差目标 MAE ~0.6-1%
  TOP10_ONLY—— 只有前十大，非重仓部分退化为按上期行业结构外推。误差会明显放大，
               运行时会显式告警，结论要打折看。
"""

import numpy as np
import pandas as pd

from . import taxonomy as tx


# ---------------------------------------------------------------- 列名归一

_COL_ALIASES = {
    "code": ["股票代码", "代码", "证券代码", "stock_code"],
    "name": ["股票名称", "名称", "证券名称", "stock_name"],
    "pct": ["占净值比例", "占净值比例(%)", "占净值比例（%）", "持仓占比", "weight"],
    "period": ["季度", "报告期", "截止时间", "截止日期", "date", "period"],
    "industry": ["行业类别", "行业名称", "行业", "industry"],
}


def pick_col(df, key, required=True):
    """在列名混乱的免费源数据里找到目标列。"""
    cols = {str(c).strip(): c for c in df.columns}
    for alias in _COL_ALIASES[key]:
        if alias in cols:
            return cols[alias]
    for alias in _COL_ALIASES[key]:
        for c in cols:
            if alias in c:
                return cols[c]
    if required:
        raise KeyError(f"找不到 [{key}] 对应的列，实际列名：{list(df.columns)}")
    return None


def parse_pct(s):
    """'12.34%' / '12.34' / 12.34 -> 0.1234"""
    if pd.isna(s):
        return np.nan
    if isinstance(s, (int, float)):
        return float(s) / 100.0
    t = str(s).strip().replace("%", "").replace(",", "")
    try:
        return float(t) / 100.0
    except ValueError:
        return np.nan


def normalize_period(s):
    """把各种报告期写法归一到 'YYYY-MM-DD' 的季末日期。

    akshare 的季度列常见形如 '2024年3季度股票投资明细'、'2024-06-30'。
    """
    t = str(s).strip()
    # 直接是日期
    m = pd.to_datetime(t, errors="coerce")
    if pd.notna(m):
        return m.normalize()
    # 'YYYY年N季度'
    import re
    mm = re.search(r"(\d{4})\s*年\s*(\d)\s*季度", t)
    if mm:
        y, q = int(mm.group(1)), int(mm.group(2))
        end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[q]
        return pd.Timestamp(f"{y}-{end}")
    return pd.NaT


# ---------------------------------------------------------------- 主流程

class SimulatedPortfolio:
    """单只基金的季度模拟组合构建器。"""

    def __init__(self, holdings, industry_alloc, stock2sw, verbose=True):
        """
        holdings        : akshare fund_portfolio_hold_em 的原始表
        industry_alloc  : akshare fund_portfolio_industry_allocation_em 的原始表
        stock2sw        : dict 股票代码(6位) -> 申万一级行业名
        """
        self.stock2sw = stock2sw
        self.verbose = verbose
        self.diagnostics = []

        self.hold = self._prep_holdings(holdings)
        self.alloc = self._prep_alloc(industry_alloc)
        self.mode = self._detect_mode()

    # ---------- 预处理

    def _prep_holdings(self, df):
        df = df.copy()
        c_code = pick_col(df, "code")
        c_pct = pick_col(df, "pct")
        c_per = pick_col(df, "period")
        c_name = pick_col(df, "name", required=False)

        out = pd.DataFrame({
            "code": df[c_code].astype(str).str.extract(r"(\d{6})")[0],
            "pct": df[c_pct].map(parse_pct),
            "period": df[c_per].map(normalize_period),
        })
        if c_name is not None:
            out["name"] = df[c_name].astype(str)
        out = out.dropna(subset=["code", "pct", "period"])
        out = out[out["pct"] > 0]
        out["sw"] = out["code"].map(self.stock2sw)
        out = out.drop_duplicates(["period", "code"])
        return out.sort_values(["period", "pct"], ascending=[True, False])

    def _prep_alloc(self, df):
        if df is None or len(df) == 0:
            return pd.DataFrame(columns=["period", "industry", "pct"])
        df = df.copy()
        c_ind = pick_col(df, "industry")
        c_pct = pick_col(df, "pct")
        c_per = pick_col(df, "period")
        out = pd.DataFrame({
            "industry": df[c_ind].astype(str),
            "pct": df[c_pct].map(parse_pct),
            "period": df[c_per].map(normalize_period),
        }).dropna(subset=["period", "pct"])
        return out

    def _detect_mode(self):
        """判断是否拿得到全部持股。"""
        n_by_period = self.hold.groupby("period").size()
        if len(n_by_period) == 0:
            return "EMPTY"
        mx = int(n_by_period.max())
        if mx > 15:
            full_periods = n_by_period[n_by_period > 15].index.tolist()
            self._log(f"模式 = FULL（{len(full_periods)} 期有全部持股，最多 {mx} 只）")
            self.full_periods = set(full_periods)
            return "FULL"
        self._log(f"模式 = TOP10_ONLY（每期最多 {mx} 只，只有前十大）")
        self._log("  ⚠ 非重仓部分只能按上期行业结构外推，误差会明显放大，结论请打折看")
        self.full_periods = set()
        return "TOP10_ONLY"

    def _historical_industries(self):
        """该基金历史上出现过的申万行业集合（缓存）。"""
        if not hasattr(self, "_hist_ind"):
            self._hist_ind = set(self.hold["sw"].dropna().unique())
        return self._hist_ind

    def _log(self, msg):
        self.diagnostics.append(msg)
        if self.verbose:
            print(f"  {msg}")

    # ---------- 核心：单期构建

    def build_period(self, period, prev_nonkey=None):
        """构建某一报告期的模拟组合（申万一级行业权重）。

        prev_nonkey : dict 申万行业 -> 权重，上一期的非重仓结构（惯性来源）
        返回 (industry_weights: dict, nonkey_structure: dict, info: dict)
        """
        hp = self.hold[self.hold["period"] == period]
        if len(hp) == 0:
            return None, prev_nonkey, {"error": "该期无持股数据"}

        # 若该期本身就是全持股，直接用，不需要补全
        if period in self.full_periods:
            w = hp.groupby("sw")["pct"].sum().to_dict()
            w = {k: v for k, v in w.items() if pd.notna(k)}
            # 非重仓结构 = 剔除前十大之后的部分
            top10 = set(hp.nlargest(10, "pct")["code"])
            nk = hp[~hp["code"].isin(top10)]
            nk_struct = nk.groupby("sw")["pct"].sum().to_dict()
            nk_struct = {k: v for k, v in nk_struct.items() if pd.notna(k)}
            return w, nk_struct, {"source": "real_full", "n_stocks": len(hp)}

        # --- 只有重仓股，需要补全
        key = hp.nlargest(10, "pct")
        w_key = key.groupby("sw")["pct"].sum().to_dict()
        w_key = {k: v for k, v in w_key.items() if pd.notna(k)}
        key_total = sum(w_key.values())
        min_key_w = float(key["pct"].min()) if len(key) else 0.0

        # 行业配置约束
        ap = self.alloc[self.alloc["period"] == period]
        groups = tx.build_group_constraints(
            list(zip(ap["industry"], ap["pct"] * 100))) if len(ap) else []

        if not groups:
            # 没有行业约束表 -> 只能按上期结构等比放大
            return self._fallback_scale(w_key, prev_nonkey, key_total, period)

        cov = tx.constraint_coverage(groups)
        weights = dict(w_key)
        nonkey_struct = {}

        for g in groups:
            members = [m for m in g["sw_members"] if m in tx.SW_NAME_TO_CODE]
            key_in_g = sum(w_key.get(m, 0.0) for m in members)
            gap = max(g["target"] - key_in_g, 0.0)
            if gap <= 1e-6:
                continue

            # 组内分配，优先级从高到低：
            #   1) 上期非重仓结构（研报的持仓惯性假设）
            #   2) 当期重仓股在组内的结构（基金的配置意图）
            #   3) 该基金历史上出现过的行业（至少别灌到它从没碰过的行业）
            #   4) 组内均分（最后兜底）
            # 早期版本直接跳到 4)，会把制造业缺口平摊到 15 个行业上，
            # 包括基金根本没配过的，误差被显著放大。
            prior = {}
            if prev_nonkey:
                prior = {m: prev_nonkey.get(m, 0.0) for m in members}
            if sum(prior.values()) <= 1e-9:
                prior = {m: w_key.get(m, 0.0) for m in members}
            if sum(prior.values()) <= 1e-9:
                hist = self._historical_industries()
                prior = {m: (1.0 if m in hist else 0.0) for m in members}
            s = sum(prior.values())
            if s > 1e-9:
                alloc_in_g = {m: gap * prior[m] / s for m in members if prior[m] > 0}
            else:
                alloc_in_g = {m: gap / len(members) for m in members}

            for m, v in alloc_in_g.items():
                weights[m] = weights.get(m, 0.0) + v
                nonkey_struct[m] = nonkey_struct.get(m, 0.0) + v

        info = {
            "source": "simulated",
            "n_key": len(key),
            "key_total": key_total,
            "min_key_weight": min_key_w,
            "constraint": cov,
            "n_groups": len(groups),
        }
        return weights, nonkey_struct, info

    def _fallback_scale(self, w_key, prev_nonkey, key_total, period):
        """没有行业配置表时的降级路径：按上期非重仓结构等比补到合理仓位。"""
        self._log(f"{period.date()} 无行业配置表，降级为纯上期结构外推")
        target_equity = 0.88   # 主动权益的经验仓位
        gap = max(target_equity - key_total, 0.0)
        weights = dict(w_key)
        nk = {}
        if prev_nonkey:
            s = sum(prev_nonkey.values())
            if s > 1e-9:
                for m, v in prev_nonkey.items():
                    add = gap * v / s
                    weights[m] = weights.get(m, 0.0) + add
                    nk[m] = add
        return weights, nk, {"source": "fallback_scale", "warning": "无行业约束"}

    # ---------- 全期递归

    def build_all(self):
        """按时间顺序递归构建所有报告期的模拟组合。

        返回 DataFrame: period × 申万行业 的权重矩阵
        """
        periods = sorted(self.hold["period"].unique())
        rows, infos = [], []
        prev_nk = None

        for p in periods:
            w, nk, info = self.build_period(p, prev_nk)
            if w is None:
                continue
            row = {"period": p}
            row.update(w)
            rows.append(row)
            info["period"] = p
            infos.append(info)
            if nk:
                prev_nk = nk

        if not rows:
            return pd.DataFrame(), pd.DataFrame()

        mat = pd.DataFrame(rows).set_index("period")
        # 补齐所有申万行业列
        for name in tx.SW_L1.values():
            if name not in mat.columns:
                mat[name] = 0.0
        mat = mat[sorted(tx.SW_L1.values())].fillna(0.0)

        return mat, pd.DataFrame(infos)

    # ---------- 个股配方导出（供 stock_level 因子构建）
    def build_stock_recipe(self):
        """按时间顺序递归构建所有报告期的个股→行业→权重配方。

        返回 (recipe: DataFrame, stock_info: dict)。

        recipe 列：[period, code, sw, weight]
        stock_info: period → {code: sw_industry}

        关键设计——缺口分配（审计修复 2026-08-07）：
        - FULL 期：全部持股直接使用，权重 = 真实持仓
        - TOP10_ONLY 期：前十大用真实权重，行业缺口分配到**上期
          FULL 期的非重仓候选池**（而非当期已披露的十只股硬扛）
        
        旧版只用当期已披露股票分配缺口 → 非重仓 15% 全压在前十大上，
        虚增权重 ~75%，行业子组合分散度塌缩 → β 系统性偏小约 25%
        （这正是 Σβ 0.671 的根因，不是 EIV 衰减）。
        """
        periods = sorted(self.hold["period"].unique())
        stock_rows = []
        stock_info = {}  # period → {code: sw}
        prev_nk = None
        # 上期 FULL 期的全部个股 → 权重（缺口分配的候选池）
        prev_full_stocks = {}  # code → (sw, weight)

        for p in periods:
            hp = self.hold[self.hold["period"] == p]
            if len(hp) == 0:
                continue

            w, nk, _ = self.build_period(p, prev_nk)
            if w is None:
                continue

            stock_info[p] = dict(zip(hp["code"], hp["sw"]))

            if p in self.full_periods:
                # ---- FULL：全部持股直接用 ----
                this_stocks = {}
                for _, s in hp.iterrows():
                    stock_rows.append({
                        "period": p, "code": s["code"],
                        "sw": s["sw"], "weight": s["pct"],
                    })
                    this_stocks[s["code"]] = (s["sw"], s["pct"])
                prev_full_stocks = this_stocks

            else:
                # ---- TOP10_ONLY：前十大真实 + 缺口分给候选池 ----
                key = hp.nlargest(10, "pct")
                key_codes_set = set(key["code"])

                # 前十大：真实权重
                key_by_sw = {}
                for _, s in key.iterrows():
                    stock_rows.append({
                        "period": p, "code": s["code"],
                        "sw": s["sw"], "weight": s["pct"],
                    })
                    sw = s["sw"]
                    key_by_sw[sw] = key_by_sw.get(sw, 0.0) + s["pct"]

                # 分配缺口到上一期 FULL 期的非重仓候选池
                if prev_full_stocks:
                    for sw_name, sw_weight in w.items():
                        key_wt = key_by_sw.get(sw_name, 0.0)
                        gap = sw_weight - key_wt
                        if gap <= 1e-8:
                            continue

                        # 候选：上期 FULL 期该行业股票，排除当期前十大已有
                        candidates = {
                            code: cand_wt
                            for code, (cs, cand_wt) in prev_full_stocks.items()
                            if cs == sw_name and code not in key_codes_set
                        }
                        total_c = sum(candidates.values())
                        if total_c <= 1e-9:
                            continue

                        for code, cand_wt in candidates.items():
                            alloc = gap * (cand_wt / total_c)
                            stock_rows.append({
                                "period": p, "code": code,
                                "sw": sw_name, "weight": alloc,
                            })

            if nk:
                prev_nk = nk

        if not stock_rows:
            return pd.DataFrame(), {}

        recipe = pd.DataFrame(stock_rows)
        return recipe, stock_info


# ---------------------------------------------------------------- 校验

def validate_holdout(sp):
    """留一法校验（唯一诚实的还原误差口径）。

    对每个有真实全持股的报告期，**假装只拿到前十大**重新构建一次模拟组合，
    再与真实行业分布比较。

    为什么必须这么做：FULL 模式下年报期直接用了真实持仓，
    如果拿这些期去比对，等于拿答案对答案，MAE 恒等于 0 —— 这个数字是假的。

    返回 (总体MAE, 分行业MAE, 制造业组MAE, 逐期明细)
    """
    if sp.mode != "FULL" or not sp.full_periods:
        return None, None, None, None

    periods = sorted(sp.hold["period"].unique())
    rows, details = [], []
    prev_nk = None

    for p in periods:
        is_holdout = p in sp.full_periods
        if is_holdout:
            # 临时把该期从"全持股期"里摘掉，强制走补全路径
            sp.full_periods.discard(p)
            w_est, nk_est, info = sp.build_period(p, prev_nk)
            sp.full_periods.add(p)

            hp = sp.hold[sp.hold["period"] == p]
            w_true = hp.groupby("sw")["pct"].sum().to_dict()
            w_true = {k: v for k, v in w_true.items() if pd.notna(k)}

            if w_est:
                cols = sorted(set(w_est) | set(w_true))
                a = np.array([w_est.get(c, 0.0) for c in cols])
                b = np.array([w_true.get(c, 0.0) for c in cols])
                rows.append(pd.Series(np.abs(a - b), index=cols))
                details.append({
                    "报告期": p.date(),
                    "MAE": float(np.abs(a - b).mean()),
                    "真实股票数": len(hp),
                    "前5大命中": len(set(pd.Series(a, index=cols).nlargest(5).index) &
                                  set(pd.Series(b, index=cols).nlargest(5).index)),
                })

        # 递归推进：用真实结构做下一期的惯性来源
        w, nk, _ = sp.build_period(p, prev_nk)
        if nk:
            prev_nk = nk

    if not rows:
        return None, None, None, None

    err = pd.DataFrame(rows).fillna(0.0)
    per_industry = err.mean(axis=0).sort_values(ascending=False)
    overall = float(err.values.mean())
    manu = [m for m in tx.CSRC_TO_SW["C"] if m in per_industry.index]
    manu_mae = float(per_industry.loc[manu].mean()) if manu else np.nan

    return overall, per_industry, manu_mae, pd.DataFrame(details)


def validate_against_real(sim_mat, real_holdings, stock2sw):
    """用真实全持股期检验模拟组合的还原误差。

    返回 (总体MAE, 分行业MAE表, 制造业组MAE)
    """
    real = real_holdings.copy()
    real["sw"] = real["code"].map(stock2sw)
    real_mat = (real.dropna(subset=["sw"])
                    .groupby(["period", "sw"])["pct"].sum()
                    .unstack(fill_value=0.0))

    common = sim_mat.index.intersection(real_mat.index)
    if len(common) == 0:
        return None, None, None

    cols = sorted(set(sim_mat.columns) | set(real_mat.columns))
    a = sim_mat.reindex(index=common, columns=cols).fillna(0.0)
    b = real_mat.reindex(index=common, columns=cols).fillna(0.0)

    abs_err = (a - b).abs()
    per_industry = abs_err.mean(axis=0).sort_values(ascending=False)
    overall = float(abs_err.values.mean())

    manu = [m for m in tx.CSRC_TO_SW["C"] if m in per_industry.index]
    manu_mae = float(per_industry.loc[manu].mean()) if manu else np.nan

    return overall, per_industry, manu_mae
