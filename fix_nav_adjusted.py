# -*- coding: utf-8 -*-
"""把 nav.csv 的 nav_cum 重建为"复权净值"。

背景：东财累计净值 = 单位净值 + 累计分红（简单相加，不复利）。
分红多的老基金，用累计净值算日收益会被系统性压缩（单位/累计 倍），
导致净值回归的 Σβ（权益仓位估计）严重偏低。
正确做法：单位净值日收益 + 除息日把分红加回分子，再累乘。

用法：python fix_nav_adjusted.py <基金代码>
"""
import os
import re
import sys
import time
from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://fundf10.eastmoney.com/fhsp.html",
}


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def fetch_dividends(code, retry=3):
    """天天基金 fhsp 页的分红送配表。"""
    url = f"https://fundf10.eastmoney.com/fhsp_{code}.html"
    for i in range(retry):
        try:
            r = requests.get(url, headers=HEADERS, timeout=180)
            r.encoding = "utf-8"
            tables = pd.read_html(StringIO(r.text))
            for tb in tables:
                cols = [str(c) for c in tb.columns]
                if any("除息日" in c for c in cols) and any("每份分红" in c or "分红" in c for c in cols):
                    return tb
            log(f"  页面抓到但没找到分红表，共 {len(tables)} 个表")
            return None
        except Exception as e:
            log(f"  retry {i+1}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(4 * (i + 1))
    return None


def main(code):
    fdir = os.path.join(ROOT, "funds", code)
    nav_path = os.path.join(fdir, "nav.csv")
    nav = pd.read_csv(nav_path, parse_dates=["date"]).sort_values("date")
    unit = pd.to_numeric(nav["nav_unit"], errors="coerce")

    div = fetch_dividends(code)
    div_map = {}
    if div is not None:
        dcol = next(c for c in div.columns if "除息日" in str(c))
        acol = next((c for c in div.columns if "分红" in str(c)
                     and "登记" not in str(c) and "发放" not in str(c)), None)
        if acol is not None:
            per10 = "10" in str(acol)  # 每10份分红 -> 要除以10
            for _, r in div.iterrows():
                d = pd.to_datetime(str(r[dcol])[:10], errors="coerce")
                txt = str(r[acol])
                mnum = re.search(r"([\d.]+)\s*元", txt)
                amt = float(mnum.group(1)) if mnum else np.nan
                if "10份" in txt:
                    amt = amt / 10.0
                elif per10:
                    amt = amt / 10.0
                if pd.notna(d) and pd.notna(amt) and amt > 0:
                    div_map[d] = div_map.get(d, 0.0) + float(amt)
    log(f"分红记录 {len(div_map)} 条，最近: "
        f"{sorted(div_map.items())[-3:] if div_map else '无'}")

    nav = nav.set_index("date")
    ret = unit.values / unit.shift(1).values - 1.0
    ret = pd.Series(ret, index=nav.index)
    n_fix = 0
    for d, amt in div_map.items():
        # 除息日（或其后第一个交易日）修正
        idx = nav.index.searchsorted(d)
        if idx < len(nav):
            real_d = nav.index[idx]
            prev = unit.shift(1).iloc[idx]
            if pd.notna(prev) and prev > 0:
                ret.iloc[idx] = (unit.iloc[idx] + amt) / prev - 1.0
                n_fix += 1
    log(f"修正除息日 {n_fix} 天")

    adj = (1 + ret.fillna(0)).cumprod()
    nav["nav_cum_raw"] = nav["nav_cum"]      # 留底
    nav["nav_cum"] = adj.values               # 复权净值（归一到首日）
    nav.reset_index().to_csv(nav_path, index=False, encoding="utf-8-sig")
    log(f"[SAVE] nav.csv 已用复权净值覆盖 nav_cum（原值存 nav_cum_raw）")

    # 快速验证：复权后对市场 beta
    idx = pd.read_csv(os.path.join(ROOT, "base", "sw_industry_index.csv"),
                      parse_dates=["date"])
    wide = idx.pivot_table(index="date", columns="industry_name", values="close")
    mkt = wide.pct_change().mean(axis=1)
    f = nav["nav_cum"].pct_change()
    df = pd.concat([f, mkt], axis=1, keys=["f", "m"]).dropna()
    for start in ["2024-01-01", "2025-07-01"]:
        sub = df[df.index >= start]
        beta = np.polyfit(sub["m"], sub["f"], 1)[0]
        log(f"复权后 {start} 起 beta={beta:.2f}（应≈0.9）")


if __name__ == "__main__":
    main(sys.argv[1].zfill(6))
