"""Independent holdings-disclosure coverage diagnostics.

This module intentionally does not feed the portfolio, regression, calibration,
or reporting paths.  It only describes the coverage of locally available
holdings disclosures.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


TOP10_MAX_ROWS = 12
COV_USABLE = 0.90
COV_FULL = 0.97
SEVERE_FLAGS = {
    "SOURCE_UNVERIFIED", "TOPLINE_LIMIT", "TOPLINE_RESPONSE_UNRELIABLE",
    "DUPLICATE", "PERIOD_MIXED", "MALFORMED",
}


def report_type_for_period(period_end) -> str:
    date = pd.to_datetime(period_end, errors="coerce")
    if pd.isna(date):
        return "UNKNOWN"
    return {
        (3, 31): "Q1",
        (6, 30): "INTERIM",
        (9, 30): "Q3",
        (12, 31): "ANNUAL",
    }.get((date.month, date.day), "UNKNOWN")


def parse_period_end(value):
    """Parse ISO dates or the local ``YYYY年N季度`` holdings label."""
    text = str(value).strip()
    match = re.search(r"(20\d{2})年\s*([1-4])季度", text)
    if match:
        return pd.Period(f"{match.group(1)}Q{match.group(2)}", freq="Q").end_time.normalize()
    return pd.to_datetime(text, errors="coerce").normalize()


def percent_to_fraction(values):
    """Convert the source's percent-labelled ratio fields to fractions."""
    text = values.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(text, errors="coerce") / 100.0


def _column(frame, candidates):
    return next((name for name in candidates if name in frame.columns), None)


def _topline_for_period(topline_used, period):
    if isinstance(topline_used, dict):
        return int(topline_used.get(pd.Timestamp(period).strftime("%Y-%m-%d"), 100))
    return int(topline_used)


def _classification(n_rows, coverage, topline, report_type, flags, alloc_available):
    if n_rows == 0:
        return "UNKNOWN", "NO_HOLDINGS_ROWS"
    if not alloc_available and n_rows > TOP10_MAX_ROWS:
        return "UNKNOWN", "REPORTED_EQUITY_MISSING"
    if n_rows <= TOP10_MAX_ROWS and (pd.isna(coverage) or coverage < COV_USABLE):
        return "TOP10", "TOP10_ROW_PATTERN"
    if report_type in {"Q1", "Q3"}:
        return "PARTIAL", "QUARTERLY_SOURCE_UNVERIFIED"
    if pd.isna(coverage):
        return "UNKNOWN", "COVERAGE_UNAVAILABLE"
    if coverage < COV_USABLE:
        return "PARTIAL", "COVERAGE_LT_0_90"
    if n_rows >= topline:
        return "TOP_N_TRUNCATED", "ROWS_AT_TOPLINE"
    if coverage >= COV_FULL and not (set(flags) & SEVERE_FLAGS):
        return "FULL_CONFIRMED", "COVERAGE_AND_ROWCOUNT_CONFIRMED"
    return "PARTIAL", "COVERAGE_BELOW_FULL_CONFIRMATION"


def build_disclosure_index(
    holdings,
    industry_alloc,
    topline_used=100,
    fund_code="UNKNOWN",
    holdings_source_status="TOPLINE_100_LOCAL",
):
    """Build one conservative diagnostic record for each disclosed period.

    ``holdings`` and ``industry_alloc`` remain untouched.  Their source ratio
    columns are percentage values and are converted to unitless fractions only
    in the returned index.
    """
    holdings = holdings.copy()
    industry_alloc = industry_alloc.copy()
    holdings_period_col = _column(holdings, ("period_end", "period", "季度"))
    alloc_period_col = _column(industry_alloc, ("period_end", "period", "截止时间"))
    holding_weight_col = _column(holdings, ("holding_pct", "pct", "占净值比例"))
    alloc_weight_col = _column(industry_alloc, ("allocation_pct", "pct", "占净值比例"))
    code_col = _column(holdings, ("stock_code", "code", "股票代码"))

    if holdings_period_col is None:
        holdings["_period_end"] = pd.NaT
    else:
        holdings["_period_end"] = holdings[holdings_period_col].map(parse_period_end)
    if alloc_period_col is None:
        industry_alloc["_period_end"] = pd.NaT
    else:
        industry_alloc["_period_end"] = industry_alloc[alloc_period_col].map(parse_period_end)
    holdings["_weight"] = percent_to_fraction(holdings[holding_weight_col]) if holding_weight_col else np.nan
    industry_alloc["_weight"] = percent_to_fraction(industry_alloc[alloc_weight_col]) if alloc_weight_col else np.nan

    periods = sorted(set(holdings["_period_end"].dropna()) | set(industry_alloc["_period_end"].dropna()))
    rows = []
    for period in periods:
        holding_slice = holdings.loc[holdings["_period_end"] == period]
        alloc_slice = industry_alloc.loc[industry_alloc["_period_end"] == period]
        n_rows = int(len(holding_slice))
        report_type = report_type_for_period(period)
        flags = []
        if holding_slice["_weight"].isna().any():
            flags.append("MALFORMED")
        codes = (
            holding_slice[code_col].astype(str).str.extract(r"(\d+)", expand=False)
            if code_col is not None else pd.Series(index=holding_slice.index, dtype=object)
        )
        if code_col is None or codes.isna().any():
            flags.append("MALFORMED")
        elif codes.duplicated().any():
            flags.append("DUPLICATE")
        if holding_slice["_period_end"].isna().any():
            flags.append("MALFORMED")
        if report_type in {"Q1", "Q3"} and n_rows > TOP10_MAX_ROWS:
            flags.extend(("QUARTERLY_PARTIAL", "SOURCE_UNVERIFIED"))
        topline = _topline_for_period(topline_used, period)
        if n_rows >= topline:
            flags.append("TOPLINE_LIMIT")
        if holdings_source_status and holdings_source_status != "TOPLINE_100_LOCAL":
            flags.append(holdings_source_status)

        holdings_sum = float(holding_slice["_weight"].sum(min_count=1)) if n_rows else 0.0
        alloc_available = len(alloc_slice) > 0 and alloc_slice["_weight"].notna().any()
        reported_equity = float(alloc_slice["_weight"].sum(min_count=1)) if alloc_available else np.nan
        coverage = holdings_sum / reported_equity if alloc_available and reported_equity > 0 else np.nan
        gap = reported_equity - holdings_sum if alloc_available and reported_equity > 0 else np.nan
        coverage_type, coverage_reason = _classification(
            n_rows, coverage, topline, report_type, flags, alloc_available
        )
        flags = sorted(set(flags))
        rows.append({
            "fund_code": str(fund_code).zfill(6),
            "period_end": pd.Timestamp(period).strftime("%Y-%m-%d"),
            "report_type": report_type,
            "n_rows": n_rows,
            "topline_used": topline,
            "holdings_sum": holdings_sum,
            "reported_equity_ratio": reported_equity,
            "coverage_ratio": coverage,
            "coverage_gap": gap,
            "min_holding_pct": float(holding_slice["_weight"].min()) if n_rows else np.nan,
            "max_holding_pct": float(holding_slice["_weight"].max()) if n_rows else np.nan,
            "coverage_type": coverage_type,
            "coverage_reason": coverage_reason,
            "holdings_source_status": "SOURCE_UNVERIFIED" if "SOURCE_UNVERIFIED" in flags else holdings_source_status,
            "alloc_source_status": "AVAILABLE" if alloc_available else "MISSING",
            "available_date": "",
            "available_date_status": "UNVERIFIED",
            "flags": ";".join(flags),
        })
    return pd.DataFrame(rows)
