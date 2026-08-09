# -*- coding: utf-8 -*-
"""
生成与 fetch_data.py 产出格式完全一致的合成数据，用于端到端联调。

用法：
    python tests/make_fake_data.py <目标目录>

会在目标目录下写出 base/ 和 funds/999999/，
然后就可以在该目录跑 run_analysis.py 999999 验证全链路。
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import taxonomy as tx
from tests.test_e2e_synthetic import make_market, make_fund, make_reports

CSRC_NAMES = {
    "A": "A农、林、牧、渔业", "B": "B采矿业", "C": "C制造业",
    "D": "D电力、热力、燃气及水生产和供应业", "E": "E建筑业",
    "F": "F批发和零售业", "G": "G交通运输、仓储和邮政业",
    "H": "H住宿和餐饮业", "I": "I信息传输、软件和信息技术服务业",
    "J": "J金融业", "K": "K房地产业", "L": "L租赁和商务服务业",
    "M": "M科学研究和技术服务业", "N": "N水利、环境和公共设施管理业",
    "O": "O居民服务、修理和其他服务业", "P": "P教育",
    "Q": "Q卫生和社会工作", "R": "R文化、体育和娱乐业", "S": "S综合",
}


def main(dest, code="999999", full_annual=True):
    base = os.path.join(dest, "base")
    fdir = os.path.join(dest, "funds", code)
    os.makedirs(base, exist_ok=True)
    os.makedirs(fdir, exist_ok=True)

    dates, ind_ret, stock_ret, stock2ind = make_market()
    W_true, stock_w, nav, active = make_fund(dates, ind_ret, stock_ret, stock2ind)
    holdings, alloc, real_hold = make_reports(dates, stock_w, stock2ind)

    # --- base/sw_industry_index.csv（长表，与 fetch_data 一致）
    rows = []
    for ind in ind_ret.columns:
        close = (1 + ind_ret[ind]).cumprod() * 1000
        for d, v in close.items():
            rows.append({"date": d.strftime("%Y-%m-%d"), "close": round(v, 4),
                         "industry_code": tx.SW_NAME_TO_CODE[ind],
                         "industry_name": ind})
    pd.DataFrame(rows).to_csv(os.path.join(base, "sw_industry_index.csv"),
                              index=False, encoding="utf-8-sig")

    # --- base/stock_industry_map.csv
    pd.DataFrame([{"股票代码": c, "industry_name": i}
                  for c, i in sorted(stock2ind.items())]
                 ).to_csv(os.path.join(base, "stock_industry_map.csv"),
                          index=False, encoding="utf-8-sig")

    pd.DataFrame([{"industry_code": k, "industry_name": v, "source": "fake"}
                  for k, v in tx.SW_L1.items()]
                 ).to_csv(os.path.join(base, "sw_industry_list.csv"),
                          index=False, encoding="utf-8-sig")

    # --- funds/<code>/nav.csv
    nav_out = nav.copy()
    nav_out["date"] = nav_out["date"].dt.strftime("%Y-%m-%d")
    nav_out["nav_unit"] = nav_out["nav_cum"]
    nav_out.to_csv(os.path.join(fdir, "nav.csv"), index=False, encoding="utf-8-sig")

    # --- funds/<code>/holdings.csv
    hold_out = holdings.copy()
    if full_annual:
        # 模拟"年报能拿到全部持股"的情形：把半年报/年报期的全持股并进去
        extra = []
        for _, r in real_hold.iterrows():
            extra.append({"股票代码": r["code"], "股票名称": f"股票{r['code']}",
                          "占净值比例": round(r["pct"] * 100, 4),
                          "季度": pd.Timestamp(r["period"]).strftime("%Y-%m-%d")})
        ex = pd.DataFrame(extra)
        # 年报期用全持股替换掉只有前十大的那份
        ann = set(ex["季度"])
        hold_out = pd.concat([hold_out[~hold_out["季度"].isin(ann)], ex],
                             ignore_index=True)
    hold_out.to_csv(os.path.join(fdir, "holdings.csv"),
                    index=False, encoding="utf-8-sig")

    # --- funds/<code>/industry_alloc.csv
    alloc.to_csv(os.path.join(fdir, "industry_alloc.csv"),
                 index=False, encoding="utf-8-sig")

    # --- 真实仓位存一份，供人工核对
    W_true.to_csv(os.path.join(dest, "_TRUTH_weights.csv"), encoding="utf-8-sig")

    print(f"合成数据已写入 {dest}")
    print(f"  行业指数 {len(rows)} 行 | 个股映射 {len(stock2ind)} 只")
    print(f"  持股 {len(hold_out)} 行（含全持股期：{full_annual}）")
    print(f"  行业配置 {len(alloc)} 行 | 净值 {len(nav_out)} 行")
    print(f"  真实活跃行业：{', '.join(sorted(active))}")


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fh_test"
    full = "--top10only" not in sys.argv
    main(dest, full_annual=full)
