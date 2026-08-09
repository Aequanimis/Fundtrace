#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal, non-production topline audit for FundArchivesDatas holdings."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch_holdings_manual import HEADERS, URL, parse_year  # noqa: E402


CODE = "161005"
PERIODS = {
    "2024-06-30": (2024, "2024年2季度股票投资明细"),
    "2025-12-31": (2025, "2025年4季度股票投资明细"),
}
TOPLINES = (100, 200, 500)
EVIDENCE_DIR = ROOT / "tests" / "evidence" / "topline_test"


def request_year(year: int, topline: int):
    last_error = ""
    for attempt in range(2):
        try:
            response = requests.get(
                URL,
                params={
                    "type": "jjcc",
                    "code": CODE,
                    "topline": str(topline),
                    "year": str(year),
                    "month": "",
                    "rt": "0.1234567890123456",
                },
                headers={**HEADERS, "Referer": f"https://fundf10.eastmoney.com/ccmx_{CODE}.html"},
                timeout=30,
            )
            response.raise_for_status()
            return response, ""
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                time.sleep(1)
    return None, last_error


def as_fraction(values):
    numeric = pd.to_numeric(
        values.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False),
        errors="coerce",
    )
    # FundArchivesDatas renders this field as a percentage string (for example
    # ``5.61%``); the audit stores a unitless fraction consistently.
    return numeric / 100.0


def normalised_rows(frame):
    result = frame.copy()
    result["股票代码"] = result["股票代码"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    result["_weight"] = as_fraction(result["占净值比例"])
    return result


def first_100_equal(frame, top100):
    if top100 is None or len(frame) < 100 or len(top100) < 100:
        return None
    columns = ["股票代码", "_weight"]
    left = normalised_rows(frame).iloc[:100][columns].reset_index(drop=True)
    right = normalised_rows(top100).iloc[:100][columns].reset_index(drop=True)
    return bool(left["股票代码"].equals(right["股票代码"]) and left["_weight"].equals(right["_weight"]))


def target_frame(frames, label):
    candidates = [frame for frame in frames if set(frame.get("季度", pd.Series(dtype=str)).astype(str)) == {label}]
    return candidates[0] if candidates else None


def audit():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    top100_frames = {}
    for period, (year, label) in PERIODS.items():
        for topline in TOPLINES:
            response, error = request_year(year, topline)
            record = {
                "fund_code": CODE,
                "period_end": period,
                "topline": topline,
                "http_success": response is not None,
                "http_status": response.status_code if response is not None else None,
                "status": "ERROR" if response is None else "OK",
                "error": error,
                "rows": None,
                "unique_stock_codes": None,
                "duplicate_stock_codes": None,
                "holdings_sum": None,
                "min_holding_pct": None,
                "max_holding_pct": None,
                "returned_report_periods": "",
                "period_mixed": None,
                "first_100_equal_top100": None,
                "has_rows_after_100": None,
                "rows_after_100_weight_sum": None,
            }
            if response is not None:
                try:
                    frames = parse_year(response.text, CODE, year)
                    frame = target_frame(frames, label)
                    if frame is None:
                        record.update({
                            "status": "TARGET_PERIOD_MISSING",
                            "error": f"missing {label}; returned={sorted({str(x) for f in frames for x in f['季度'].unique()})}",
                        })
                    else:
                        prepared = normalised_rows(frame)
                        weights = prepared["_weight"]
                        report_periods = sorted(prepared["季度"].astype(str).unique())
                        record.update({
                            "rows": len(prepared),
                            "unique_stock_codes": int(prepared["股票代码"].nunique()),
                            "duplicate_stock_codes": bool(prepared["股票代码"].duplicated().any()),
                            "holdings_sum": float(weights.sum()),
                            "min_holding_pct": float(weights.min()),
                            "max_holding_pct": float(weights.max()),
                            "returned_report_periods": "|".join(report_periods),
                            "period_mixed": len(report_periods) != 1 or report_periods != [label],
                            "first_100_equal_top100": first_100_equal(prepared, top100_frames.get(period)),
                            "has_rows_after_100": len(prepared) > 100,
                            "rows_after_100_weight_sum": float(weights.iloc[100:].sum()) if len(prepared) > 100 else 0.0,
                        })
                        prepared.drop(columns="_weight").to_csv(
                            EVIDENCE_DIR / f"{period.replace('-', '')}_top{topline}.csv",
                            index=False,
                            encoding="utf-8-sig",
                        )
                        if topline == 100:
                            top100_frames[period] = prepared
                except Exception as exc:  # evidence must record parser failures instead of fabricating files
                    record.update({"status": "PARSE_ERROR", "error": f"{type(exc).__name__}: {exc}"})
            rows.append(record)
    summary = pd.DataFrame(rows)
    summary.to_csv(EVIDENCE_DIR / "summary.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    audit()
