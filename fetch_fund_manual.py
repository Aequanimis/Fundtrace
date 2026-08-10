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
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone, timedelta
from io import StringIO
from pathlib import Path

import requests
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))
ACTIVE_LOG_PATH = None

STAGE_METADATA = "FUND_METADATA"
STAGE_NAV = "NAV"
STAGE_HOLDINGS = "HOLDINGS"
STAGE_INDUSTRY = "INDUSTRY_ALLOCATION"
STAGE_SAVE = "SAVE"
STAGE_OTHER = "OTHER"


class FetchError(RuntimeError):
    def __init__(self, stage, code, message, detail=""):
        super().__init__(detail or message)
        self.stage = stage
        self.code = code
        self.message = message
        self.detail = detail

    def payload(self):
        return {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class TimeoutError_(Exception):
    pass


def configure_fetch_log(code, logs_dir=None):
    global ACTIVE_LOG_PATH
    directory = Path(logs_dir or Path(ROOT) / "logs")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ACTIVE_LOG_PATH = directory / f"fetch_{code}_{stamp}.log"
    return ACTIVE_LOG_PATH


def log(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    if ACTIVE_LOG_PATH is not None:
        with ACTIVE_LOG_PATH.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")


def normalize_fund_code(code):
    value = str(code).strip()
    if not re.fullmatch(r"\d{6}", value):
        raise FetchError(
            STAGE_METADATA,
            "INVALID_FUND_CODE",
            "基金代码格式无效",
            "fund code must contain exactly six digits",
        )
    return value


def _temporary_path(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    return Path(name)


def atomic_write_csv(frame, destination):
    destination = Path(destination)
    temporary = _temporary_path(destination)
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        os.replace(temporary, destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise FetchError(
            STAGE_SAVE,
            "FUND_DATA_SAVE_FAILED",
            "基金数据保存失败",
            f"{type(exc).__name__}: {exc}",
        ) from exc


def atomic_write_json(payload, destination):
    destination = Path(destination)
    temporary = _temporary_path(destination)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise FetchError(
            STAGE_SAVE,
            "FUND_DATA_SAVE_FAILED",
            "基金数据保存失败",
            f"{type(exc).__name__}: {exc}",
        ) from exc


def require_columns(frame, required, stage, code):
    if frame is None or frame.empty:
        raise FetchError(stage, code, "公开数据返回为空")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise FetchError(
            stage,
            code,
            "公开数据字段不完整",
            f"missing columns: {', '.join(missing)}",
        )


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


def parse_fund_name(js_path):
    txt = Path(js_path).read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'var\s+fS_name\s*=\s*"([^"]+)"', txt)
    if not match:
        raise FetchError(
            STAGE_METADATA,
            "PUBLIC_FUND_METADATA_FAILED",
            "基金基本信息获取失败",
            "fS_name is missing from pingzhongdata response",
        )
    return match.group(1).strip()


def parse_nav(js_path, fdir=None, code=None):
    txt = Path(js_path).read_text(encoding="utf-8", errors="ignore")
    m1 = re.search(r"var\s+Data_netWorthTrend\s*=\s*(\[.*?\]);", txt, re.S)
    m2 = re.search(r"var\s+Data_ACWorthTrend\s*=\s*(\[.*?\]);", txt, re.S)
    if not m1:
        raise FetchError(
            STAGE_NAV,
            "PUBLIC_NAV_PARSE_FAILED",
            "基金净值公开数据解析失败",
            "Data_netWorthTrend is missing",
        )
    try:
        unit = json.loads(m1.group(1))
    except json.JSONDecodeError as exc:
        raise FetchError(
            STAGE_NAV,
            "PUBLIC_NAV_PARSE_FAILED",
            "基金净值公开数据解析失败",
            f"JSONDecodeError: {exc}",
        ) from exc
    if not unit:
        raise FetchError(
            STAGE_NAV,
            "PUBLIC_NAV_EMPTY",
            "基金净值公开数据为空",
        )
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
    nav["nav_unit"] = pd.to_numeric(nav["nav_unit"], errors="coerce")
    if "nav_cum" in nav:
        nav["nav_cum"] = pd.to_numeric(nav["nav_cum"], errors="coerce")
    nav = nav.dropna(subset=["date", "nav_unit"]).sort_values("date")
    nav = nav.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    require_columns(nav, ("date", "nav_unit", "nav_cum"), STAGE_NAV, "PUBLIC_NAV_SCHEMA_INVALID")
    log(f"stage=NAV source=eastmoney status=SUCCESS rows={len(nav)} start={nav['date'].iloc[0]} end={nav['date'].iloc[-1]}")
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
                if not m:
                    continue
                amt = float(m.group(1))
                if per10:
                    amt = amt / 10.0
                if pd.notna(d) and amt > 0:
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
    partial = f"{dest}.part"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
               "Referer": f"https://fund.eastmoney.com/{code}.html"}
    log(f"stage=NAV source=eastmoney event=start url=pingzhongdata/{code}.js")
    for i in range(max_retry):
        try:
            start = os.path.getsize(partial) if os.path.exists(partial) else 0
            h = dict(headers)
            if start:
                h["Range"] = f"bytes={start}-"
            r = requests.get(url, headers=h, timeout=300, stream=True)
            if r.status_code not in (200, 206):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            mode = "ab" if (start and r.status_code == 206) else "wb"
            with open(partial, mode) as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            txt = Path(partial).read_text(encoding="utf-8", errors="ignore")
            if "Data_netWorthTrend" in txt and "Data_ACWorthTrend" in txt:
                os.replace(partial, dest)
                log(f"stage=NAV source=eastmoney event=download status=SUCCESS bytes={os.path.getsize(dest)}")
                return dest
            log(f"stage=NAV source=eastmoney status=RETRY attempt={i+1} reason=incomplete_response")
        except Exception as e:
            log(f"stage=NAV source=eastmoney status=RETRY attempt={i+1} error={type(e).__name__}:{str(e)[:120]}")
        time.sleep(3)
    raise FetchError(
        STAGE_NAV,
        "PUBLIC_NAV_FETCH_FAILED",
        "基金净值公开数据获取失败",
        "pingzhongdata download failed after retries",
    )


def fetch_yearly_table(
    code,
    years,
    fetch_function,
    stage,
    error_code,
    required_columns,
    retries=2,
    timeout_seconds=240,
):
    parts = []
    errors = []
    for year in years:
        for attempt in range(retries):
            try:
                frame = run_with_timeout(
                    lambda year=year: fetch_function(symbol=code, date=year),
                    timeout_seconds,
                )
                if frame is not None and not frame.empty:
                    require_columns(frame, required_columns, stage, error_code)
                    frame = frame.copy()
                    frame["fetch_year"] = year
                    parts.append(frame)
                    log(
                        f"stage={stage} source=akshare_eastmoney status=SUCCESS "
                        f"year={year} rows={len(frame)}"
                    )
                    break
                errors.append(f"{year}:empty")
                log(
                    f"stage={stage} source=akshare_eastmoney status=EMPTY "
                    f"year={year} attempt={attempt + 1}"
                )
            except FetchError:
                raise
            except Exception as exc:
                errors.append(f"{year}:{type(exc).__name__}:{exc}")
                log(
                    f"stage={stage} source=akshare_eastmoney status=RETRY "
                    f"year={year} attempt={attempt + 1} "
                    f"error={type(exc).__name__}:{str(exc)[:120]}"
                )
                if attempt + 1 < retries:
                    time.sleep(3)
        time.sleep(1.5)
    if not parts:
        message = (
            "基金净值已获取，但公开持仓数据获取失败"
            if stage == STAGE_HOLDINGS
            else "基金净值和持仓已获取，但公开行业配置获取失败"
        )
        raise FetchError(stage, error_code, message, "; ".join(errors[-8:]))
    combined = pd.concat(parts, ignore_index=True)
    require_columns(combined, required_columns, stage, error_code)
    return combined


def fetch_holdings(code, years, ak_module, **kwargs):
    return fetch_yearly_table(
        code,
        years,
        ak_module.fund_portfolio_hold_em,
        STAGE_HOLDINGS,
        "PUBLIC_HOLDINGS_FETCH_FAILED",
        ("股票代码", "股票名称", "占净值比例", "季度"),
        **kwargs,
    )


def fetch_industry_allocation(code, years, ak_module, **kwargs):
    return fetch_yearly_table(
        code,
        years,
        ak_module.fund_portfolio_industry_allocation_em,
        STAGE_INDUSTRY,
        "PUBLIC_INDUSTRY_ALLOCATION_FETCH_FAILED",
        ("行业类别", "占净值比例", "截止时间"),
        **kwargs,
    )


def main(code, js_path=None, root=ROOT, ak_module=None, logs_dir=None):
    if ak_module is None:
        import akshare as ak_module

    code = normalize_fund_code(code)
    log_path = configure_fetch_log(code, logs_dir)
    started = time.monotonic()
    log(f"fund_code={code} event=fetch_start")
    fdir = Path(root) / "funds" / code
    fdir.mkdir(parents=True, exist_ok=True)

    if js_path is None:
        js_path = fdir / f"pingzhongdata_{code}.js"
        js_path = download_js(code, str(js_path))

    fund_name = parse_fund_name(js_path)
    log(f"stage={STAGE_METADATA} source=eastmoney status=SUCCESS name={fund_name}")

    nav = add_adjusted_nav(parse_nav(js_path, fdir, code), code)
    require_columns(
        nav,
        ("date", "nav_unit", "nav_cum", "nav_adj"),
        STAGE_NAV,
        "PUBLIC_NAV_SCHEMA_INVALID",
    )
    atomic_write_csv(nav[["date", "nav_unit", "nav_cum", "nav_adj"]], fdir / "nav.csv")
    log(f"stage={STAGE_SAVE} item=nav.csv status=SUCCESS rows={len(nav)}")

    years = [str(year) for year in range(datetime.now().year - 4, datetime.now().year + 1)]
    holdings = fetch_holdings(code, years, ak_module)
    atomic_write_csv(holdings, fdir / "holdings.csv")
    log(f"stage={STAGE_SAVE} item=holdings.csv status=SUCCESS rows={len(holdings)}")

    allocation = fetch_industry_allocation(code, years, ak_module)
    atomic_write_csv(allocation, fdir / "industry_alloc.csv")
    log(f"stage={STAGE_SAVE} item=industry_alloc.csv status=SUCCESS rows={len(allocation)}")

    payload = {
        "fund_code": code,
        "fund_name": fund_name,
        "fetched_at": datetime.now().isoformat(),
        "mode": "manual",
        "items": {
            "metadata": {"ok": True, "name": fund_name},
            "nav": {"ok": True, "rows": len(nav), "note": "含 nav_adj 复权净值"},
            "holdings": {"ok": True, "rows": len(holdings)},
            "industry_alloc": {"ok": True, "rows": len(allocation)},
            "aum": {"ok": False, "err": "skipped (manual mode)"},
        },
    }
    atomic_write_json(payload, fdir / "_fund_manifest.json")
    elapsed = time.monotonic() - started
    result = {
        "status": "SUCCESS",
        "fund_code": code,
        "fund_name": fund_name,
        "nav_rows": len(nav),
        "holdings_rows": len(holdings),
        "industry_alloc_rows": len(allocation),
        "elapsed_seconds": round(elapsed, 3),
        "log_path": str(log_path),
    }
    log(f"fund_code={code} event=fetch_complete elapsed_seconds={elapsed:.3f}")
    print("FETCH_RESULT_JSON " + json.dumps(result, ensure_ascii=False), flush=True)
    return result


def cli(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("用法: python fetch_fund_manual.py <6位基金代码> [pingzhongdata.js路径]", file=sys.stderr)
        return 2
    code = arguments[0]
    js_path = arguments[1] if len(arguments) > 1 else None
    try:
        main(code, js_path)
        return 0
    except FetchError as exc:
        log(
            f"fund_code={code} event=fetch_failed stage={exc.stage} "
            f"code={exc.code} error={exc.detail or str(exc)}"
        )
        print("FETCH_ERROR_JSON " + json.dumps(exc.payload(), ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        log(f"fund_code={code} event=fetch_failed stage={STAGE_OTHER} error={detail}")
        if ACTIVE_LOG_PATH is not None:
            with ACTIVE_LOG_PATH.open("a", encoding="utf-8", newline="\n") as handle:
                traceback.print_exc(file=handle)
        payload = FetchError(
            STAGE_OTHER,
            "PUBLIC_FUND_FETCH_FAILED",
            "公开基金数据获取失败",
            detail,
        ).payload()
        print("FETCH_ERROR_JSON " + json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
