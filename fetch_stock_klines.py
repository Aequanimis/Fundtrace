#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量抓取个股日K线 → 全局缓存 base/stock_klines.csv

用法：
    python fetch_stock_klines.py <基金代码>          # 抓该基金全部持仓
    python fetch_stock_klines.py <基金代码> --force  # 强制全量刷新（含已缓存）

缓存逻辑：
    全局 base/stock_klines.csv 为 date × code × close 长表。
    每次运行自动 diff：只抓缓存里没有的股票代码，增量追加。
    新基金跑过第一只后，后续基金基本只需拉几十只新代码。

数据源：
    proxy.finance.qq.com 腾讯财经 K 线（qfq 前复权），无鉴权限流。
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from lib.simulate import normalize_period, pick_col

CACHE_FILE = os.path.join(ROOT, "base", "stock_klines.csv")
KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
MAX_WORKERS = 8
START_DATE = "2019-01-01"
END_DATE = "2026-06-30"


def tencent_symbol(code):
    """6位股票代码 → 腾讯符号"""
    code = str(code).zfill(6)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_one(symbol):
    """抓取单只股票前复权日K线。返回 list of (date, close) 或 None。"""
    params = {
        "_var": "kline_dayqfq",
        "param": f"{symbol},day,{START_DATE},{END_DATE},1200,qfq",
        "r": str(time.time()),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://proxy.finance.qq.com/",
    }
    for attempt in range(3):
        try:
            r = requests.get(KLINE_URL, params=params, headers=headers, timeout=15)
            r.encoding = "utf-8"
            m = re.search(r"kline_dayqfq=(.*)", r.text, re.S)
            if not m:
                continue
            data = json.loads(m.group(1))
            stock = data.get("data", {}).get(symbol, {})
            klines = stock.get("qfqday", []) or stock.get("day", [])
            if not klines:
                return None
            # kline: [date, open, close, high, low, volume, {...}, chg%, amount, ...]
            code = symbol.replace("sh", "").replace("sz", "")
            return [(k[0], code, k[2]) for k in klines if len(k) >= 3]
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


def load_cache():
    """加载全局缓存 → dict (date, code) → close."""
    if not os.path.exists(CACHE_FILE):
        return {}
    df = pd.read_csv(CACHE_FILE, dtype={"date": str, "code": str})
    return {(r["date"], r["code"]): r["close"] for _, r in df.iterrows()}


def extract_fund_codes(fund_code):
    """提取基金所有历史持仓中的股票代码。"""
    fdir = os.path.join(ROOT, "funds", fund_code)
    hold_path = os.path.join(fdir, "holdings.csv")
    if not os.path.exists(hold_path):
        sys.exit(f"找不到 {hold_path}")
    hold = pd.read_csv(hold_path, dtype=str)
    period_col = pick_col(hold, "period")
    hold["period"] = hold[period_col].map(normalize_period)
    codes = hold["股票代码"].dropna().unique()
    return sorted(str(c).zfill(6) for c in codes)


def main():
    ap = argparse.ArgumentParser(description="批量抓取个股日K线到全局缓存")
    ap.add_argument("code", help="6位基金代码")
    ap.add_argument("--force", action="store_true", help="强制刷新所有代码（忽略已有缓存）")
    args = ap.parse_args()

    code = args.code.zfill(6)
    all_codes = extract_fund_codes(code)
    existing = load_cache()
    cached_codes = set(c for _, c in existing)
    needed = all_codes if args.force else [c for c in all_codes if c not in cached_codes]

    if not needed:
        print(f"基金 {code}：{len(all_codes)} 只股票全部已缓存，无需抓取。")
        return

    print(f"基金 {code}：{len(all_codes)} 只股票，已缓存 {len(cached_codes)}，需抓取 {len(needed)}")

    symbols = [tencent_symbol(c) for c in needed]
    seen = dict(existing)  # copy
    fetched = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s): s for s in symbols}
        for i, f in enumerate(as_completed(futures), 1):
            result = f.result()
            if result:
                fetched += 1
                for date_val, code_val, close_val in result:
                    seen[(date_val, code_val)] = close_val
            else:
                failed += 1
            if i % 20 == 0:
                print(f"  ... {i}/{len(symbols)}, fetched {fetched}, failed {failed}")

    # 去重 + 排序 + 写入
    sorted_keys = sorted(seen.keys(), key=lambda x: (x[1], x[0]))
    with open(CACHE_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "close"])
        for (d, c), v in seen.items():
            w.writerow([d, c, v])

    total_codes = len(set(c for _, c in seen))
    print(f"完成：{len(seen)} 行，{total_codes} 只股票（抓取{len(needed)}只，新增{fetched}，失败{failed}）")
    if failed:
        print(f"  ⚠ {failed} 只抓取失败，可重试：python fetch_stock_klines.py {code}")


if __name__ == "__main__":
    main()
