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
SERIOUS_ALLOC_SOURCE_STATUSES = {"MISSING", "MALFORMED", "ERROR"}
ALLOC_ANNOUNCEMENT_DATE_COLUMNS = (
    "alloc_announcement_date", "announcement_date", "publish_date",
    "published_at", "公告日期", "公告日", "披露日期", "披露日", "发布日期",
)


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


def _format_date(value):
    date = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(date) else pd.Timestamp(date).strftime("%Y-%m-%d")


def _truthy(values):
    """Accept native booleans and CSV round-tripped boolean strings."""
    if isinstance(values, pd.Series):
        return values.map(_truthy)
    if isinstance(values, (bool, np.bool_)):
        return bool(values)
    return str(values).strip().lower() in {"1", "true", "yes", "y"}


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
    alloc_announcement_col = _column(industry_alloc, ALLOC_ANNOUNCEMENT_DATE_COLUMNS)

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
        actual_alloc_dates = pd.Series(dtype="datetime64[ns]")
        if alloc_announcement_col is not None:
            actual_alloc_dates = pd.to_datetime(
                alloc_slice[alloc_announcement_col], errors="coerce"
            ).dropna()
        if len(actual_alloc_dates):
            # An industry allocation is fully usable only after its latest
            # local announcement record is public.
            alloc_available_date = actual_alloc_dates.max().normalize()
            alloc_available_status = "ACTUAL_SOURCE_DATE"
            alloc_available_source = alloc_announcement_col
        else:
            # Local source files contain report periods but no actual
            # announcement date.  This is a conservative availability
            # assumption, not a claim about the real publication date.
            alloc_available_date = pd.Timestamp(period) + pd.Timedelta(days=30)
            alloc_available_status = "CONSERVATIVE_30D_FALLBACK"
            alloc_available_source = "period_end + 30 calendar days"
        alloc_source_status = "AVAILABLE" if alloc_available else "MISSING"
        valid_reported_equity = bool(
            np.isfinite(reported_equity) and 0.0 < reported_equity <= 1.5
        )
        cap_eligible = bool(
            valid_reported_equity
            and pd.notna(alloc_available_date)
            and alloc_source_status not in SERIOUS_ALLOC_SOURCE_STATUSES
        )
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
            "alloc_source_status": alloc_source_status,
            "alloc_available_date": _format_date(alloc_available_date),
            "alloc_available_date_status": alloc_available_status,
            "alloc_available_date_source": alloc_available_source,
            "holdings_available_date": "",
            "holdings_available_date_status": "UNVERIFIED_PHASE_B3",
            "cap_eligible": cap_eligible,
            "available_date": "",
            "available_date_status": "UNVERIFIED",
            "flags": ";".join(flags),
        })
    return pd.DataFrame(rows)


def resolve_equity_cap(disclosure_index, date, hard_max=0.98, fallback=0.95):
    """Resolve a point-in-time equity cap from field-level disclosures.

    Allocation availability is deliberately independent of holdings coverage.
    Only allocation records available on or before ``date`` can set the normal
    cap.  The tightly restricted full-holdings fallback is retained for a
    future B3 data source; PARTIAL, TOP10 and TOP_N_TRUNCATED rows are never
    used as a cap source.
    """
    hard_max = float(hard_max)
    fallback = float(fallback)
    if not np.isfinite(hard_max) or not np.isfinite(fallback):
        raise ValueError("hard_max and fallback must be finite")
    if hard_max <= 0 or fallback <= 0:
        raise ValueError("hard_max and fallback must be positive")
    as_of = pd.to_datetime(date, errors="coerce")
    if pd.isna(as_of):
        raise ValueError("date must be a valid date")
    as_of = pd.Timestamp(as_of).normalize()
    fallback_cap = min(fallback, hard_max)

    def result(cap_value, basis, source_period=None, source_available_date=None,
               reported_equity_ratio=None, flags=""):
        return {
            "cap_value": float(min(float(cap_value), hard_max)),
            "cap_basis": basis,
            "source_period": source_period,
            "source_available_date": source_available_date,
            "reported_equity_ratio": reported_equity_ratio,
            "flags": flags,
        }

    if disclosure_index is None or len(disclosure_index) == 0:
        return result(fallback_cap, "CONSTANT_FALLBACK", flags="NO_VISIBLE_ALLOC")

    frame = disclosure_index.copy()
    if "period_end" not in frame:
        return result(fallback_cap, "CONSTANT_FALLBACK", flags="NO_VISIBLE_ALLOC")
    frame["_period_end"] = pd.to_datetime(frame["period_end"], errors="coerce").dt.normalize()
    frame["_alloc_available_date"] = pd.to_datetime(
        frame.get("alloc_available_date", pd.Series(index=frame.index, dtype=object)),
        errors="coerce",
    ).dt.normalize()
    frame["_reported_equity_ratio"] = pd.to_numeric(
        frame.get("reported_equity_ratio", pd.Series(index=frame.index, dtype=object)),
        errors="coerce",
    )
    eligible = _truthy(frame.get("cap_eligible", pd.Series(False, index=frame.index)))
    alloc_status = frame.get("alloc_source_status", pd.Series("AVAILABLE", index=frame.index))
    alloc_status = alloc_status.astype(str).str.upper()
    valid_ratio = (
        np.isfinite(frame["_reported_equity_ratio"])
        & (frame["_reported_equity_ratio"] > 0)
        & (frame["_reported_equity_ratio"] <= 1.5)
    )
    visible_alloc = frame.loc[
        eligible
        & valid_ratio
        & frame["_alloc_available_date"].notna()
        & (frame["_alloc_available_date"] <= as_of)
        & ~alloc_status.isin(SERIOUS_ALLOC_SOURCE_STATUSES)
    ].sort_values(["_period_end", "_alloc_available_date"])
    if len(visible_alloc):
        row = visible_alloc.iloc[-1]
        ratio = float(row["_reported_equity_ratio"])
        return result(
            min(ratio * 1.05, hard_max),
            "INDUSTRY_ALLOC",
            source_period=_format_date(row["_period_end"]),
            source_available_date=_format_date(row["_alloc_available_date"]),
            reported_equity_ratio=ratio,
        )

    # B3-only fallback: it requires an explicit, visible holdings date and a
    # FULL_CONFIRMED record.  The B2 index intentionally leaves this date blank.
    frame["_holdings_available_date"] = pd.to_datetime(
        frame.get("holdings_available_date", pd.Series(index=frame.index, dtype=object)),
        errors="coerce",
    ).dt.normalize()
    frame["_holdings_sum"] = pd.to_numeric(
        frame.get("holdings_sum", pd.Series(index=frame.index, dtype=object)), errors="coerce"
    )
    coverage_type = frame.get("coverage_type", pd.Series("", index=frame.index))
    visible_full_holdings = frame.loc[
        coverage_type.astype(str).str.upper().eq("FULL_CONFIRMED")
        & np.isfinite(frame["_holdings_sum"])
        & (frame["_holdings_sum"] > 0)
        & frame["_holdings_available_date"].notna()
        & (frame["_holdings_available_date"] <= as_of)
    ].sort_values(["_period_end", "_holdings_available_date"])
    if len(visible_full_holdings):
        row = visible_full_holdings.iloc[-1]
        holdings_sum = float(row["_holdings_sum"])
        return result(
            min(holdings_sum * 1.05, hard_max),
            "FULL_CONFIRMED_HOLDINGS",
            source_period=_format_date(row["_period_end"]),
            source_available_date=_format_date(row["_holdings_available_date"]),
            reported_equity_ratio=None,
            flags="NO_VISIBLE_ALLOC",
        )

    return result(fallback_cap, "CONSTANT_FALLBACK", flags="NO_VISIBLE_ALLOC")
