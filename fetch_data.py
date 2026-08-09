#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公募基金高频仓位测算 —— 数据抓取脚本（申万一级口径，全部免费源）

用法：
    python fetch_data.py base                 # 抓底座数据（一次性，一季度刷新一次）
    python fetch_data.py fund 001234          # 抓单只基金的数据
    python fetch_data.py probe 001234         # 探测：年报/半年报能否直接拿到全部持股
    python fetch_data.py fund 001234 --years 2022 2023 2024 2025 2026

依赖：
    pip install akshare pandas

产出目录结构：
    fund_highfreq/
      base/
        sw_industry_index.csv     申万一级行业指数日线（长表）
        sw_industry_list.csv      申万一级行业代码表
        stock_industry_map.csv    个股 -> 申万行业 映射（含历史变更）
        benchmark_weight.csv      中证全指成分权重（算 overweight 用）
        _base_manifest.json       抓取时间 / 各项成败记录
      funds/
        001234/
          nav.csv                 日度单位净值 + 累计净值
          holdings.csv            各报告期持股（重仓股，年报/半年报可能是全部持股）
          industry_alloc.csv      证监会行业配置（Step1 的强约束）
          aum.csv                 规模历史
          _fund_manifest.json
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime

import pandas as pd

try:
    import akshare as ak
except ImportError:
    sys.exit("缺少 akshare，请先执行：pip install akshare pandas")


# ---------------------------------------------------------------- 配置

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(ROOT, "base")
FUNDS_DIR = os.path.join(ROOT, "funds")

# 申万 2021 版一级行业（31 个）。优先从接口取，取不到用这份兜底。
SW_L1_FALLBACK = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁",
    "801050": "有色金属", "801080": "电子",     "801110": "家用电器",
    "801120": "食品饮料", "801130": "纺织服饰", "801140": "轻工制造",
    "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产",   "801200": "商贸零售", "801210": "社会服务",
    "801230": "综合",     "801710": "建筑材料", "801720": "建筑装饰",
    "801730": "电力设备", "801740": "国防军工", "801750": "计算机",
    "801760": "传媒",     "801770": "通信",     "801780": "银行",
    "801790": "非银金融", "801880": "汽车",     "801890": "机械设备",
    "801950": "煤炭",     "801960": "石油石化", "801970": "环保",
    "801980": "美容护理",
}

# 中证全指，用作 overweight 的基准
BENCHMARK_INDEX = "000985"

RETRY = 3
SLEEP = 1.2   # 对免费源客气一点，避免被限流


# ---------------------------------------------------------------- 工具

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def attempt(label, fn, retry=RETRY):
    """带重试的调用。失败不抛出，返回 (df_or_None, err_str_or_None)。

    免费数据源经常抽风，单项失败不应该让整次抓取报废。
    """
    last = None
    for i in range(retry):
        try:
            out = fn()
            if out is None or (hasattr(out, "empty") and out.empty):
                raise ValueError("返回空数据")
            log(f"  [OK]   {label}  rows={len(out)}")
            return out, None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if i < retry - 1:
                time.sleep(SLEEP * (i + 1))
    log(f"  [FAIL] {label}  {last}")
    return None, last


def save(df, path, label):
    if df is None:
        return False
    ensure_dir(os.path.dirname(path))
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log(f"  [SAVE] {label} -> {os.path.relpath(path, ROOT)}  ({len(df)} 行)")
    return True


# ---------------------------------------------------------------- 底座

def fetch_industry_list():
    """申万一级行业代码表。接口不稳，失败则用内置兜底。"""
    df, err = attempt("申万一级行业列表", ak.sw_index_first_info)
    if df is not None:
        # 不同版本列名不一致，做个宽松映射
        cols = {c: c for c in df.columns}
        code_col = next((c for c in df.columns if "代码" in c or c.lower() == "code"), None)
        name_col = next((c for c in df.columns if "名称" in c or c.lower() == "name"), None)
        if code_col and name_col:
            out = df[[code_col, name_col]].copy()
            out.columns = ["industry_code", "industry_name"]
            out["industry_code"] = out["industry_code"].astype(str).str.extract(r"(\d{6})")[0]
            out = out.dropna(subset=["industry_code"]).drop_duplicates("industry_code")
            if len(out) >= 28:
                out["source"] = "api"
                return out
        log("  [WARN] 接口返回的列名无法识别，改用内置兜底行业表")

    log("  [WARN] 使用内置申万一级行业表（31 个）")
    return pd.DataFrame(
        [{"industry_code": k, "industry_name": v, "source": "fallback"}
         for k, v in SW_L1_FALLBACK.items()]
    )


def fetch_base():
    ensure_dir(BASE_DIR)
    manifest = {"fetched_at": datetime.now().isoformat(), "items": {}}

    # --- 1. 行业列表
    log("步骤 1/4  申万一级行业列表")
    ind_list = fetch_industry_list()
    save(ind_list, os.path.join(BASE_DIR, "sw_industry_list.csv"), "行业列表")
    manifest["items"]["industry_list"] = {"ok": True, "n": len(ind_list),
                                          "source": ind_list["source"].iloc[0]}

    # --- 2. 行业指数日线（逐个抓，31 次请求）
    log(f"步骤 2/4  申万一级行业指数日线（{len(ind_list)} 个，约需 1-3 分钟）")
    frames, failed = [], []
    for _, row in ind_list.iterrows():
        code, name = row["industry_code"], row["industry_name"]
        df, err = attempt(f"{code} {name}",
                          lambda c=code: ak.index_hist_sw(symbol=c, period="day"))
        if df is None:
            failed.append({"code": code, "name": name, "err": err})
            continue
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        date_col = next((c for c in df.columns if "日期" in c or c.lower() == "date"), df.columns[0])
        close_col = next((c for c in df.columns if "收盘" in c or c.lower() == "close"), None)
        if close_col is None:
            failed.append({"code": code, "name": name, "err": f"找不到收盘价列，实际列={list(df.columns)}"})
            continue
        out = df[[date_col, close_col]].copy()
        out.columns = ["date", "close"]
        out["industry_code"] = code
        out["industry_name"] = name
        frames.append(out)
        time.sleep(SLEEP)

    if frames:
        idx = pd.concat(frames, ignore_index=True)
        idx["date"] = pd.to_datetime(idx["date"], errors="coerce")
        idx = idx.dropna(subset=["date", "close"]).sort_values(["industry_code", "date"])
        save(idx, os.path.join(BASE_DIR, "sw_industry_index.csv"), "行业指数日线")
        manifest["items"]["industry_index"] = {
            "ok": True, "n_industries": idx["industry_code"].nunique(),
            "date_min": str(idx["date"].min().date()),
            "date_max": str(idx["date"].max().date()),
            "failed": failed,
        }
    else:
        manifest["items"]["industry_index"] = {"ok": False, "failed": failed}
        log("  [ERROR] 行业指数一个都没抓到 —— 这是硬依赖，必须解决")

    # --- 3. 个股行业映射（含历史变更）
    log("步骤 3/4  个股 -> 申万行业 映射（含历史变更）")
    smap, err = attempt("个股行业分类历史", ak.stock_industry_clf_hist_sw)
    if smap is None:
        # 兜底：用各行业当前成分股拼一张（没有历史变更信息）
        log("  [WARN] 历史分类接口失败，改用各行业当前成分股拼接（无历史沿革，会有回溯偏差）")
        parts = []
        for _, row in ind_list.iterrows():
            d, e = attempt(f"成分股 {row['industry_code']} {row['industry_name']}",
                           lambda c=row["industry_code"]: ak.index_component_sw(symbol=c),
                           retry=2)
            if d is not None:
                d = d.copy()
                d["industry_code"] = row["industry_code"]
                d["industry_name"] = row["industry_name"]
                parts.append(d)
            time.sleep(SLEEP)
        smap = pd.concat(parts, ignore_index=True) if parts else None
        manifest["items"]["stock_industry_map"] = {
            "ok": smap is not None, "mode": "current_constituents_fallback",
            "warning": "无历史沿革，回溯早期数据会错配行业"}
    else:
        manifest["items"]["stock_industry_map"] = {"ok": True, "mode": "hist_clf"}
    save(smap, os.path.join(BASE_DIR, "stock_industry_map.csv"), "个股行业映射")

    # --- 4. 基准权重
    log("步骤 4/4  中证全指成分权重（overweight 基准）")
    bw, err = attempt(f"中证全指 {BENCHMARK_INDEX} 权重",
                      lambda: ak.index_stock_cons_weight_csindex(symbol=BENCHMARK_INDEX))
    save(bw, os.path.join(BASE_DIR, "benchmark_weight.csv"), "基准权重")
    manifest["items"]["benchmark_weight"] = {"ok": bw is not None, "err": err}

    with open(os.path.join(BASE_DIR, "_base_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    _summary(manifest)


# ---------------------------------------------------------------- 单基金

def default_years():
    """默认抓最近 5 个自然年（含今年）。"""
    y = datetime.now().year
    return [str(x) for x in range(y - 4, y + 1)]


def fetch_fund(code, years=None):
    years = years or default_years()
    fdir = ensure_dir(os.path.join(FUNDS_DIR, code))
    manifest = {"fund_code": code, "fetched_at": datetime.now().isoformat(),
                "years": years, "items": {}}

    # --- 净值（Step 2 的被解释变量，硬依赖）
    log(f"[{code}] 1/4  日度净值")
    nav_parts = {}
    for ind in ["单位净值走势", "累计净值走势"]:
        d, e = attempt(ind, lambda i=ind: ak.fund_open_fund_info_em(
            symbol=code, indicator=i, period="成立来"))
        if d is not None:
            nav_parts[ind] = d
    if nav_parts:
        nav = None
        for ind, d in nav_parts.items():
            d = d.copy()
            d.columns = [str(c).strip() for c in d.columns]
            dc = next((c for c in d.columns if "日期" in c), d.columns[0])
            vc = next((c for c in d.columns if "净值" in c), d.columns[1])
            d = d[[dc, vc]]
            d.columns = ["date", "nav_unit" if "单位" in ind else "nav_cum"]
            nav = d if nav is None else nav.merge(d, on="date", how="outer")
        nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
        nav = nav.dropna(subset=["date"]).sort_values("date")
        save(nav, os.path.join(fdir, "nav.csv"), "净值")
        manifest["items"]["nav"] = {"ok": True, "n": len(nav),
                                    "date_min": str(nav["date"].min().date()),
                                    "date_max": str(nav["date"].max().date())}
    else:
        manifest["items"]["nav"] = {"ok": False}
        log("  [ERROR] 净值抓取失败 —— 没有净值就做不了升频，只能出季频结果")

    # --- 持股（逐年）
    log(f"[{code}] 2/4  持股明细（{', '.join(years)}）")
    hold_parts = []
    for y in years:
        d, e = attempt(f"持股 {y}", lambda yy=y: ak.fund_portfolio_hold_em(symbol=code, date=yy))
        if d is not None:
            d = d.copy()
            d["fetch_year"] = y
            hold_parts.append(d)
        time.sleep(SLEEP)
    if hold_parts:
        hold = pd.concat(hold_parts, ignore_index=True)
        save(hold, os.path.join(fdir, "holdings.csv"), "持股")
        manifest["items"]["holdings"] = {"ok": True, "n": len(hold),
                                         "years_ok": [p["fetch_year"].iloc[0] for p in hold_parts]}
    else:
        manifest["items"]["holdings"] = {"ok": False}

    # --- 证监会行业配置（Step 1 的强约束）
    log(f"[{code}] 3/4  证监会行业配置")
    alloc_parts = []
    for y in years:
        d, e = attempt(f"行业配置 {y}",
                       lambda yy=y: ak.fund_portfolio_industry_allocation_em(symbol=code, date=yy))
        if d is not None:
            d = d.copy()
            d["fetch_year"] = y
            alloc_parts.append(d)
        time.sleep(SLEEP)
    if alloc_parts:
        alloc = pd.concat(alloc_parts, ignore_index=True)
        save(alloc, os.path.join(fdir, "industry_alloc.csv"), "行业配置")
        manifest["items"]["industry_alloc"] = {"ok": True, "n": len(alloc)}
    else:
        manifest["items"]["industry_alloc"] = {"ok": False}
        log("  [WARN] 行业配置缺失 —— Step1 的强约束没了，只能退化成纯重仓股外推")

    # --- 规模
    log(f"[{code}] 4/4  规模历史")
    aum, e = attempt("规模", lambda: ak.fund_aum_hist_em(year=str(datetime.now().year - 1)))
    if aum is not None:
        cc = next((c for c in aum.columns if "代码" in c), None)
        if cc:
            aum = aum[aum[cc].astype(str).str.zfill(6) == code]
    save(aum, os.path.join(fdir, "aum.csv"), "规模")
    manifest["items"]["aum"] = {"ok": aum is not None and len(aum) > 0}

    with open(os.path.join(fdir, "_fund_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    _summary(manifest)


# ---------------------------------------------------------------- 探测

def probe(code):
    """探测 akshare 对年报/半年报报告期能返回多少只股票。

    这一步决定你还需不需要上传 PDF：
      - 如果年报/半年报报告期返回几十~几百只 -> 是全部持股，PDF 可以不传
      - 如果每期都恰好 10 只                 -> 只有重仓股，年报全持股必须传 PDF
    """
    log(f"探测基金 {code} 的持股披露深度 ...")
    rows = []
    for y in default_years():
        d, e = attempt(f"持股 {y}", lambda yy=y: ak.fund_portfolio_hold_em(symbol=code, date=yy), retry=2)
        if d is None:
            continue
        d.columns = [str(c).strip() for c in d.columns]
        pcol = next((c for c in d.columns if "季度" in c or "报告期" in c or "日期" in c), None)
        if pcol is None:
            log(f"  [WARN] {y} 找不到报告期列，实际列={list(d.columns)}")
            continue
        for period, grp in d.groupby(pcol):
            rows.append({"报告期": period, "股票数": len(grp)})
        time.sleep(SLEEP)

    if not rows:
        log("探测失败：一条持股数据都没拿到。")
        return

    res = pd.DataFrame(rows).drop_duplicates().sort_values("报告期")
    print("\n" + res.to_string(index=False))

    mx = res["股票数"].max()
    print("\n" + "=" * 60)
    if mx > 15:
        print(f"结论：最多的一期有 {mx} 只股票 —— 年报/半年报能直接拿到全部持股。")
        print("      => PDF 可以不用传，全流程走 akshare。")
    else:
        print(f"结论：最多的一期只有 {mx} 只股票 —— 只有前十大重仓股。")
        print("      => 年报/半年报的全部持股必须靠上传 PDF 补。")
    print("=" * 60)


# ---------------------------------------------------------------- 汇总

def _summary(manifest):
    print("\n" + "=" * 60)
    print("抓取结果汇总")
    print("=" * 60)
    for k, v in manifest["items"].items():
        flag = "OK  " if v.get("ok") else "FAIL"
        extra = ""
        if v.get("n"):
            extra = f"  n={v['n']}"
        if v.get("date_min"):
            extra += f"  {v['date_min']} ~ {v['date_max']}"
        if v.get("warning"):
            extra += f"  ⚠ {v['warning']}"
        print(f"  [{flag}] {k}{extra}")
        for f in (v.get("failed") or [])[:5]:
            print(f"          失败: {f.get('name', f.get('code'))}  {f.get('err', '')[:80]}")
    print("=" * 60)
    print("把整个 fund_highfreq 文件夹留在原地即可，我能直接读。\n")


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="公募基金高频仓位 —— 数据抓取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("base", help="抓底座数据（一次性）")

    pf = sub.add_parser("fund", help="抓单只基金数据")
    pf.add_argument("code", help="6 位基金代码")
    pf.add_argument("--years", nargs="+", default=None, help="报告年份，默认最近 5 年")

    pp = sub.add_parser("probe", help="探测年报能否直接拿到全部持股")
    pp.add_argument("code", help="6 位基金代码")

    a = ap.parse_args()
    try:
        if a.cmd == "base":
            fetch_base()
        elif a.cmd == "fund":
            fetch_fund(a.code.zfill(6), a.years)
        elif a.cmd == "probe":
            probe(a.code.zfill(6))
    except KeyboardInterrupt:
        log("已中断。已抓到的部分都已落盘，重跑会补齐。")
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
