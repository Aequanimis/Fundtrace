# -*- coding: utf-8 -*-
"""补充抓取：申万一级行业成分股 + 重建个股行业映射。

背景：本环境访问 swsresearch.com 极慢且必须带 Referer，akshare 原生
stock_industry_clf_hist_sw / index_component_sw 会挂死。
本脚本用 UA+Referer+超时+重试 抓 31 个一级行业成分股，
结合已下载的 StockClassifyUse_stock.xls（含历史分类），
经验性地推出 分类代码前两位 -> 申万一级行业 的映射，
产出 base/stock_industry_map.csv（列：股票代码, industry_name, ...）。
"""
import json
import os
import time
from datetime import datetime

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "base")
XLS = "/tmp/sw_classify.xls"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.swsresearch.com/institute_sw/allIndex/releasedIndex",
}
URL = "https://www.swsresearch.com/institute-sw/api/index_publish/details/component_stocks/"


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def fetch_components(code, retry=3):
    for i in range(retry):
        try:
            r = requests.get(URL, params={"swindexcode": code, "page": "1",
                                          "page_size": "10000"},
                             headers=HEADERS, verify=False, timeout=180)
            data = r.json()["data"]["results"]
            if data:
                return pd.DataFrame(data)
        except Exception as e:
            log(f"  retry {i+1} {code}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(3 * (i + 1))
    return None


def main():
    ind = pd.read_csv(os.path.join(BASE, "sw_industry_list.csv"), dtype=str)
    parts, failed = [], []
    for _, row in ind.iterrows():
        code, name = row["industry_code"], row["industry_name"]
        df = fetch_components(code)
        if df is None:
            failed.append(code)
            log(f"[FAIL] {code} {name}")
            continue
        df["industry_code"] = code
        df["industry_name"] = name
        parts.append(df)
        log(f"[OK] {code} {name}  n={len(df)}")
        time.sleep(1.5)

    cons = pd.concat(parts, ignore_index=True)
    cons.to_csv(os.path.join(BASE, "sw_l1_constituents.csv"),
                index=False, encoding="utf-8-sig")

    # --- 用成分股 + xls 最新记录，推 分类代码前缀 -> 一级行业
    hist = pd.read_excel(XLS, dtype=str)
    hist["股票代码"] = hist["股票代码"].str.extract(r"(\d{6})")[0]
    hist["prefix"] = hist["行业代码"].str[:2]
    hist["计入日期"] = pd.to_datetime(hist["计入日期"], errors="coerce")
    latest = (hist.sort_values("计入日期")
                  .drop_duplicates("股票代码", keep="last")
                  .set_index("股票代码"))

    cons["stock"] = cons["stockcode"].astype(str).str.extract(r"(\d{6})")[0]
    vote = {}
    for (pfx, ind_name), grp in cons.assign(
            pfx=cons["stock"].map(latest["prefix"])).groupby(["pfx", "industry_name"]):
        if isinstance(pfx, str) and len(pfx) == 2:
            vote.setdefault(pfx, {})[ind_name] = len(grp)
    prefix2l1 = {p: max(v, key=v.get) for p, v in vote.items()}
    log(f"前缀映射（{len(prefix2l1)} 个）：{prefix2l1}")

    # --- 全量个股映射（含已退市，取最新一条记录）
    latest2 = latest.reset_index()
    latest2["industry_name"] = latest2["prefix"].map(prefix2l1)
    out = latest2.dropna(subset=["industry_name"])[
        ["股票代码", "industry_name", "行业代码", "计入日期"]]
    out = out.rename(columns={"行业代码": "sw_class_code", "计入日期": "start_date"})
    out["source"] = "swsresearch_xls+constituents"
    out.to_csv(os.path.join(BASE, "stock_industry_map.csv"),
               index=False, encoding="utf-8-sig")
    log(f"stock_industry_map.csv 写出 {len(out)} 行，覆盖股票 {out['股票代码'].nunique()} 只")

    manifest = {
        "fetched_at": datetime.now().isoformat(),
        "items": {
            "industry_list": {"ok": True, "n": 31, "source": "api"},
            "industry_index": {"ok": True, "n_industries": 31},
            "stock_industry_map": {"ok": True, "mode": "hist_clf_rebuilt",
                                   "n": int(len(out)),
                                   "failed_constituent_indexes": failed},
            "benchmark_weight": {"ok": False,
                                 "err": "csindex 接口本环境超时，overweight 暂不可用（非硬依赖）"},
        },
    }
    with open(os.path.join(BASE, "_base_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log("完成")


if __name__ == "__main__":
    main()
