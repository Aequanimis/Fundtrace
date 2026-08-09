# -*- coding: utf-8 -*-
"""手动抓取单基金数据（绕过 akshare 无超时挂死的问题）。

用法：python fetch_fund_manual.py <代码> <pingzhongdata.js路径>

产物 funds/<代码>/：
- nav.csv            nav_unit（单位净值）+ nav_cum（累计净值，仅供参考）
                     + nav_adj（复权净值：除息日把分红加回后累乘，回归用的就是这个）
- holdings.csv       akshare fund_portfolio_hold_em（逐年，带超时）
- industry_alloc.csv akshare fund_portfolio_industry_allocation_em（逐年，带超时）

注意：nav_adj 是回归的被解释变量。绝不要用 nav_cum —— 东财累计净值 =
单位净值 + 历史累计分红（简单加总，不复利），对分红多的老基金会把日收益
波动率压缩约一半，导致 Σβ 系统性腰斩。
"""
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from io import StringIO

import requests
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))


class TimeoutError_(Exception):
    pass


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def run_with_timeout(fn, secs=240):
    """跨平台超时（Windows 无 SIGALRM，用线程 join 实现）。"""
    box = {}

    def target():
        try:
            box["r"] = fn()
        except Exception as e:  # noqa
            box["e"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(secs)
    if t.is_alive():
        raise TimeoutError_(f"超时 {secs}s")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def parse_nav(js_path, fdir, code):
    txt = open(js_path, encoding="utf-8", errors="ignore").read()
    m1 = re.search(r"var\s+Data_netWorthTrend\s*=\s*(\[.*?\]);", txt, re.S)
    m2 = re.search(r"var\s+Data_ACWorthTrend\s*=\s*(\[.*?\]);", txt, re.S)
    if not m1:
        raise SystemExit("JS 里找不到 Data_netWorthTrend，下载可能不完整")
    unit = json.loads(m1.group(1))
    nav = pd.DataFrame({
        "date": [datetime.fromtimestamp(d["x"] / 1000, CST).strftime("%Y-%m-%d") for d in unit],
        "nav_unit": [d["y"] for d in unit],
    })
    if m2:
        cum = json.loads(m2.group(1))
        nc = pd.DataFrame({
            "date": [datetime.fromtimestamp(d[0] / 1000, CST).strftime("%Y-%m-%d") for d in cum],
            "nav_cum": [d[1] for d in cum],
        })
        nav = nav.merge(nc, on="date", how="outer")
    nav = nav.sort_values("date")
    nav.to_csv(os.path.join(fdir, "nav.csv"), index=False, encoding="utf-8-sig")
    log(f"[SAVE] nav.csv {len(nav)} 行  {nav['date'].iloc[0]} ~ {nav['date'].iloc[-1]}")
    return nav


def fetch_dividends(code, retry=3):
    """天天基金 fhsp 页的分红送配表。"""
    url = f"https://fundf10.eastmoney.com/fhsp_{code}.html"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"}
    for i in range(retry):
        try:
            r = requests.get(url, headers=headers, timeout=180)
            r.encoding = "utf-8"
            tables = pd.read_html(StringIO(r.text))
            for tb in tables:
                cols = [str(c) for c in tb.columns]
                if any("除息日" in c for c in cols) and any("分红" in c for c in cols):
                    return tb
            log("  分红页抓到但没找到分红表")
            return None
        except Exception as e:
            log(f"  retry {i+1} 分红: {type(e).__name__} {str(e)[:60]}")
            time.sleep(4 * (i + 1))
    return None


def add_adjusted_nav(nav, code):
    """把 nav_cum 列替换为复权净值（除息日分红加回单位净值后累乘）。

    返回写入 nav_adj 列后的 DataFrame。若抓不到分红，退化为单位净值
    （单位净值虽在除息日有小负跳，但 β 量级正确，不会被腰斩）。
    """
    nav = nav.copy()
    nav["date"] = pd.to_datetime(nav["date"])
    nav = nav.set_index("date").sort_index()
    unit = pd.to_numeric(nav["nav_unit"], errors="coerce")

    div = fetch_dividends(code)
    div_map = {}
    if div is not None:
        dcol = next(c for c in div.columns if "除息日" in str(c))
        acol = next((c for c in div.columns if "分红" in str(c)
                     and "登记" not in str(c) and "发放" not in str(c)), None)
        if acol is not None:
            per10 = ("10份" in str(acol)) or ("每10" in str(acol))
            for _, r in div.iterrows():
                d = pd.to_datetime(str(r[dcol])[:10], errors="coerce")
                m = re.search(r"([\d.]+)\s*元", str(r[acol]))
                amt = float(m.group(1)) if m else np.nan
                if per10 and pd.notna(amt):
                    amt = amt / 10.0
                if pd.notna(d) and pd.notna(amt) and amt > 0:
                    div_map[d] = div_map.get(d, 0.0) + float(amt)

    ret = unit.pct_change()
    for d, amt in div_map.items():
        i = ret.index.searchsorted(d)
        if 0 < i < len(ret):
            prev = unit.iloc[i - 1]
            if pd.notna(prev) and prev > 0:
                ret.iloc[i] = (unit.iloc[i] + amt) / prev - 1.0
    nav["nav_adj"] = (1 + ret.fillna(0)).cumprod().values
    nav = nav.reset_index()
    log(f"复权净值已写入 nav_adj（分红 {len(div_map)} 条；无分红则退化为单位净值）")
    return nav


def download_js(code, dest, max_retry=12):
    """断点续传下载天天基金 pingzhongdata 净值 JS（老基金传输慢但可续传）。"""
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
               "Referer": f"https://fund.eastmoney.com/{code}.html"}
    for i in range(max_retry):
        try:
            start = os.path.getsize(dest) if os.path.exists(dest) else 0
            h = dict(headers)
            if start:
                h["Range"] = f"bytes={start}-"
            r = requests.get(url, headers=h, timeout=300, stream=True)
            mode = "ab" if (start and r.status_code == 206) else "wb"
            with open(dest, mode) as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            txt = open(dest, encoding="utf-8", errors="ignore").read()
            if "Data_netWorthTrend" in txt and "Data_ACWorthTrend" in txt:
                log(f"[OK] 净值JS {dest} ({os.path.getsize(dest)} bytes)")
                return dest
            log(f"  [不完整] 重试 {i+1}")
        except Exception as e:
            log(f"  [retry {i+1}] 下载: {type(e).__name__} {str(e)[:60]}")
        time.sleep(3)
    raise SystemExit("净值JS下载失败（网络太慢或被限流），可手动 curl 后传路径")


def main(code, js_path=None):
    import akshare as ak
    fdir = os.path.join(ROOT, "funds", code)
    os.makedirs(fdir, exist_ok=True)

    # 不传 JS 路径则自动断点续传下载
    if js_path is None:
        js_path = os.path.join(fdir, f"pingzhongdata_{code}.js")
        js_path = download_js(code, js_path)

    nav = parse_nav(js_path, fdir, code)
    nav = add_adjusted_nav(nav, code)
    # 重新写回 nav.csv（含 nav_adj）
    nav[["date", "nav_unit", "nav_cum", "nav_adj"]].to_csv(
        os.path.join(fdir, "nav.csv"), index=False, encoding="utf-8-sig")

    years = [str(y) for y in range(datetime.now().year - 4, datetime.now().year + 1)]

    hold_parts = []
    for y in years:
        for i in range(2):
            try:
                d = run_with_timeout(
                    lambda: ak.fund_portfolio_hold_em(symbol=code, date=y), 240)
                if d is not None and not d.empty:
                    d["fetch_year"] = y
                    hold_parts.append(d)
                    log(f"[OK] 持股 {y} rows={len(d)}")
                    break
            except Exception as e:
                log(f"[retry {i+1}] 持股 {y}: {type(e).__name__} {str(e)[:60]}")
                time.sleep(3)
        time.sleep(1.5)
    if hold_parts:
        pd.concat(hold_parts, ignore_index=True).to_csv(
            os.path.join(fdir, "holdings.csv"), index=False, encoding="utf-8-sig")
        log(f"[SAVE] holdings.csv {sum(len(p) for p in hold_parts)} 行")

    alloc_parts = []
    for y in years:
        for i in range(2):
            try:
                d = run_with_timeout(
                    lambda: ak.fund_portfolio_industry_allocation_em(symbol=code, date=y), 240)
                if d is not None and not d.empty:
                    d["fetch_year"] = y
                    alloc_parts.append(d)
                    log(f"[OK] 行业配置 {y} rows={len(d)}")
                    break
            except Exception as e:
                log(f"[retry {i+1}] 行业配置 {y}: {type(e).__name__} {str(e)[:60]}")
                time.sleep(3)
        time.sleep(1.5)
    if alloc_parts:
        pd.concat(alloc_parts, ignore_index=True).to_csv(
            os.path.join(fdir, "industry_alloc.csv"), index=False, encoding="utf-8-sig")
        log(f"[SAVE] industry_alloc.csv {sum(len(p) for p in alloc_parts)} 行")

    with open(os.path.join(fdir, "_fund_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"fund_code": code, "fetched_at": datetime.now().isoformat(),
                   "mode": "manual", "items": {
                       "nav": {"ok": True, "note": "含 nav_adj 复权净值"},
                       "holdings": {"ok": bool(hold_parts)},
                       "industry_alloc": {"ok": bool(alloc_parts)},
                       "aum": {"ok": False, "err": "skipped (manual mode)"}}},
                  f, ensure_ascii=False, indent=2)
    log("完成")


if __name__ == "__main__":
    code = sys.argv[1].zfill(6)
    js_path = sys.argv[2] if len(sys.argv) > 2 else None
    main(code, js_path)
