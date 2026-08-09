# -*- coding: utf-8 -*-
"""手动重建 holdings.csv —— 绕过 akshare 对天天基金持仓页的解析 bug。

akshare fund_portfolio_hold_em 对全持股期（年报/半年报）的表格解析会
把大部分行的 占净值比例 变成 0.0。本脚本直接请求 FundArchivesDatas
原始接口，自己解 JS 转义、配对 h4 标签与表格。

用法：python fetch_holdings_manual.py <基金代码> [起始年 结束年]
"""
import os
import re
import sys
import time
from datetime import datetime
from io import StringIO

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def fetch_year(code, year, retry=3):
    for i in range(retry):
        try:
            r = requests.get(URL, params={
                "type": "jjcc", "code": code, "topline": "100",
                "year": str(year), "month": "", "rt": "0.1234567890123456",
            }, headers={**HEADERS,
                        "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html"},
                timeout=240)
            r.raise_for_status()
            return r.text
        except Exception as e:
            log(f"  retry {i+1} {year}: {type(e).__name__} {str(e)[:80]}")
            time.sleep(4 * (i + 1))
    return None


def parse_year(txt, code, year):
    """解 JS 转义后，配对 h4 季度标签与表格。"""
    m = re.search(r'content\s*:\s*"(.*)"\s*,\s*arryear', txt, re.S)
    body = m.group(1) if m else txt
    body = body.replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\")

    labels = [f"{y}年{q}季度股票投资明细"
              for y, q in re.findall(r"(20\d{2})\s*年\s*(\d)\s*季度股票投资明细", body)]
    tables = re.findall(r"<table.*?</table>", body, re.S)
    if not tables:
        return []
    if len(labels) != len(tables):
        log(f"  [WARN] {year} 标签数({len(labels)}) != 表格数({len(tables)})，按顺序尽力配对")
    frames = []
    for i, tb in enumerate(tables):
        df = pd.read_html(StringIO(tb), converters={"股票代码": str})[0]
        df = df.rename(columns={"占净值 比例": "占净值比例"})
        keep = [c for c in ["序号", "股票代码", "股票名称", "占净值比例",
                            "持股数（万股）", "持股数 （万股）",
                            "持仓市值（万元）", "持仓市值 （万元）"] if c in df.columns]
        df = df[keep].copy()
        df["季度"] = labels[i] if i < len(labels) else f"{year}表{i}"
        frames.append(df)
    return frames


def main(code, y0, y1):
    fdir = os.path.join(ROOT, "funds", code)
    os.makedirs(fdir, exist_ok=True)
    all_frames = []
    for y in range(y0, y1 + 1):
        txt = fetch_year(code, y)
        if txt is None:
            log(f"[FAIL] {y}")
            continue
        frames = parse_year(txt, code, y)
        for f in frames:
            f["fetch_year"] = str(y)
        all_frames.extend(frames)
        log(f"[OK] {y}: {len(frames)} 期 {sum(len(f) for f in frames)} 行")
        time.sleep(2)

    out = pd.concat(all_frames, ignore_index=True)
    ren = {"持股数（万股）": "持股数", "持股数 （万股）": "持股数",
           "持仓市值（万元）": "持仓市值", "持仓市值 （万元）": "持仓市值"}
    out = out.rename(columns=ren)
    out["占净值比例"] = (out["占净值比例"].astype(str)
                       .str.replace("%", "", regex=False))
    out.to_csv(os.path.join(fdir, "holdings.csv"),
               index=False, encoding="utf-8-sig")
    log(f"[SAVE] holdings.csv {len(out)} 行")
    # 各期行数速览
    print(out.groupby("季度").size().sort_index().to_string())


if __name__ == "__main__":
    code = sys.argv[1].zfill(6)
    now = datetime.now().year
    y0 = int(sys.argv[2]) if len(sys.argv) > 2 else now - 4
    y1 = int(sys.argv[3]) if len(sys.argv) > 3 else now
    main(code, y0, y1)
