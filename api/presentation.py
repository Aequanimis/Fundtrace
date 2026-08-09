"""Deterministic presentation layer over existing FundTrace output files."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
FUND_CODE_RE = re.compile(r"^\d{6}$")
CREDIBILITY_RE = re.compile(
    r"\*\*可信度评级：\s*([A-D])\s*[-—·]\s*([^*\r\n]+?)\s*\*\*"
)


def _indexed_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError(f"Empty result file: {path.name}")
    date_column = "date" if "date" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={date_column: "date"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
    if frame.empty:
        raise ValueError(f"No valid dates in result file: {path.name}")
    return frame


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _boolean(value) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _industry_item(industry: str, exposure) -> dict:
    return {"industry": str(industry), "exposure": _finite(exposure, 0.0)}


def _four_week_reference(index: pd.DatetimeIndex) -> pd.Timestamp:
    target = index[-1] - pd.Timedelta(days=28)
    eligible = index[index <= target]
    return eligible[-1] if len(eligible) else index[0]


def _summary_sentence(increase: dict, decrease: dict) -> str:
    if increase["delta"] > 0 and decrease["delta"] < 0:
        return f"近期{increase['industry']}隐含暴露上升较明显，{decrease['industry']}有所回落。"
    if increase["delta"] > 0:
        return f"近期{increase['industry']}隐含暴露上升较明显，其他行业变化相对温和。"
    if decrease["delta"] < 0:
        return f"近期{decrease['industry']}隐含暴露有所回落，未见明显增加行业。"
    return "最近四周隐含行业暴露整体变化较小。"


def parse_credibility(report_markdown: str) -> dict | None:
    """Read the model's existing A/B/C/D grade; never infer a new one."""
    match = CREDIBILITY_RE.search(report_markdown)
    if not match:
        return None
    return {
        "grade": match.group(1),
        "label": match.group(2).strip(),
        "source": "existing_model_report",
    }


def build_presentation(
    fund_code: str,
    output_root: Path | str = OUTPUT_DIR,
    analysis_time: float | None = None,
) -> dict:
    """Read existing artifacts and return frontend-safe JSON data only."""
    if not FUND_CODE_RE.fullmatch(str(fund_code)):
        raise ValueError("fund_code must contain exactly six digits")
    code = str(fund_code)
    result_dir = Path(output_root) / code
    required = {
        "weekly": result_dir / "weekly_positions.csv",
        "diagnostics": result_dir / "diagnostics.csv",
        "report": result_dir / "report.md",
    }
    missing = [path.name for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing analysis output: {', '.join(missing)}")

    weekly = _indexed_csv(required["weekly"])
    weekly = weekly.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    diagnostics = _indexed_csv(required["diagnostics"])
    latest_date = weekly.index[-1]
    latest = weekly.iloc[-1].sort_values(ascending=False)
    top_all = [_industry_item(industry, value) for industry, value in latest.items()]

    reference_date = _four_week_reference(weekly.index)
    delta = (weekly.iloc[-1] - weekly.loc[reference_date]).sort_values(ascending=False)
    changes = [
        {"industry": str(industry), "delta": _finite(value, 0.0)}
        for industry, value in delta.items()
    ]
    increases = [item for item in changes if item["delta"] > 0][:5]
    decreases = sorted(
        (item for item in changes if item["delta"] < 0), key=lambda item: item["delta"]
    )[:5]
    largest_increase = increases[0] if increases else {"industry": "—", "delta": 0.0}
    largest_decrease = decreases[0] if decreases else {"industry": "—", "delta": 0.0}

    diag_dates = diagnostics.index[diagnostics.index <= latest_date]
    latest_diag = diagnostics.loc[diag_dates[-1]] if len(diag_dates) else diagnostics.iloc[-1]
    sum_beta = _finite(latest_diag.get("sum_beta"), float(latest.sum()))
    r2 = _finite(latest_diag.get("r2"))
    converged = _boolean(latest_diag.get("converged", False))

    trend = []
    for date, row in weekly.tail(52).iterrows():
        trend.append({
            "date": date.strftime("%Y-%m-%d"),
            "values": {str(industry): _finite(value, 0.0) for industry, value in row.items()},
        })

    comparison = []
    sim_path = result_dir / "sim_portfolio.csv"
    if sim_path.is_file():
        simulated = _indexed_csv(sim_path).apply(pd.to_numeric, errors="coerce")
        disclosed_dates = simulated.index[simulated.index <= latest_date]
        if len(disclosed_dates):
            disclosed_date = disclosed_dates[-1]
            disclosed = simulated.loc[disclosed_date]
            common = latest.index.intersection(disclosed.index)
            rows = []
            for industry in common:
                base = _finite(disclosed.get(industry), 0.0)
                current = _finite(latest.get(industry), 0.0)
                rows.append({
                    "industry": str(industry),
                    "disclosed": base,
                    "current": current,
                    "delta": current - base,
                    "source_date": disclosed_date.strftime("%Y-%m-%d"),
                })
            comparison = sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)[:10]

    report_markdown = required["report"].read_text(encoding="utf-8")
    credibility = parse_credibility(report_markdown)
    analysis_seconds = _finite(analysis_time)
    payload = {
        "fund_code": code,
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "analysis_time": analysis_seconds,
        "summary": {
            "sentence": _summary_sentence(largest_increase, largest_decrease),
            "main_industry": top_all[0] if top_all else {"industry": "—", "exposure": 0.0},
            "largest_increase": largest_increase,
            "largest_decrease": largest_decrease,
            "implicit_exposure_sum": sum_beta,
        },
        "top_industries": top_all[:10],
        "all_industries": top_all,
        "four_week_changes": {
            "from_date": reference_date.strftime("%Y-%m-%d"),
            "to_date": latest_date.strftime("%Y-%m-%d"),
            "increases": increases,
            "decreases": decreases,
        },
        "trend": trend,
        "disclosure_comparison": comparison,
        "credibility": credibility,
        "diagnostics": {
            "r2": r2,
            "median_r2": _finite(pd.to_numeric(diagnostics.get("r2"), errors="coerce").median()),
            "converged": converged,
            "n_obs": int(_finite(latest_diag.get("n_obs"), 0)),
            "n_active": int(_finite(latest_diag.get("n_active"), 0)),
            "model_version": "v4-a2.1-stable",
            "mode": "Stable MVP",
            "parameters": {"window": 120, "half_life": 40, "alpha": 1e-6, "anchor": None},
            "data_cutoff": latest_date.strftime("%Y-%m-%d"),
        },
        "report_markdown": report_markdown,
        "downloads": [
            {"label": "下载完整报告", "filename": "report.md", "url": f"/api/downloads/{code}/report.md"},
            {"label": "下载周频结果", "filename": "weekly_positions.csv", "url": f"/api/downloads/{code}/weekly_positions.csv"},
            {"label": "下载诊断数据", "filename": "diagnostics.csv", "url": f"/api/downloads/{code}/diagnostics.csv"},
        ],
    }
    return payload
