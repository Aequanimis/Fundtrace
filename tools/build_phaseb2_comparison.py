#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create the concise Phase B2 legacy/disclosure comparison report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def triplet(values):
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"min": None, "median": None, "max": None}
    return {key: float(value) for key, value in {
        "min": values.min(), "median": values.median(), "max": values.max(),
    }.items()}


def pct_triplet(values):
    values = triplet(values)
    return "/".join("n/a" if value is None else f"{value:.2%}" for value in values.values())


def _read_positions(path):
    frame = pd.read_csv(path)
    date_column = "date" if "date" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={date_column: "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def top5_and_max_abs_diff(legacy_path, new_path):
    legacy = _read_positions(legacy_path)
    current = _read_positions(new_path)
    common_dates = legacy.index.intersection(current.index)
    common_cols = legacy.columns.intersection(current.columns)
    if len(common_dates) != len(legacy) or len(common_dates) != len(current):
        raise ValueError("Legacy and disclosure weekly position dates do not match")
    legacy = legacy.loc[common_dates, common_cols].apply(pd.to_numeric, errors="coerce")
    current = current.loc[common_dates, common_cols].apply(pd.to_numeric, errors="coerce")
    matches = [
        set(legacy.loc[date].nlargest(5).index) == set(current.loc[date].nlargest(5).index)
        for date in common_dates
    ]
    return float(np.mean(matches)), float((legacy - current).abs().to_numpy().max())


def q1_q3_windows(audit, disclosure_index):
    audit = audit.copy()
    audit["date"] = pd.to_datetime(audit["date"])
    index = disclosure_index.copy()
    index["alloc_available_date"] = pd.to_datetime(
        index["alloc_available_date"], errors="coerce"
    )
    rows = []
    for row in index[index["report_type"].isin(["Q1", "Q3"])].itertuples(index=False):
        if pd.isna(row.alloc_available_date):
            continue
        window = audit[
            (audit["date"] >= row.alloc_available_date)
            & (audit["date"] < row.alloc_available_date + pd.Timedelta(days=56))
        ]
        if window.empty:
            continue
        rows.append({
            "period_end": row.period_end,
            "available_date": row.alloc_available_date.strftime("%Y-%m-%d"),
            "legacy_cap_median": float(window["legacy_cap"].median()),
            "new_cap_median": float(window["new_cap"].median()),
            "legacy_sum_beta_median": float(window["legacy_sum_beta"].median()),
            "new_sum_beta_median": float(window["new_sum_beta"].median()),
        })
    return pd.DataFrame(rows)


def main(code="161005"):
    code = str(code).zfill(6)
    outdir = ROOT / "output" / code
    baseline = ROOT / "tests" / "baseline"
    audit = pd.read_csv(outdir / "equity_cap_audit.csv")
    index = pd.read_csv(ROOT / "funds" / code / "disclosure_index.csv")
    top5_consistency, max_abs_diff = top5_and_max_abs_diff(
        baseline / "phaseB2_legacy_weekly_positions.csv", outdir / "weekly_positions.csv"
    )
    q_windows = q1_q3_windows(audit, index)
    q_anomaly_reduced = bool(
        len(q_windows)
        and q_windows["new_cap_median"].min() > q_windows["legacy_cap_median"].min() + 0.10
    )
    metrics = {
        "legacy_cap": triplet(audit["legacy_cap"]),
        "new_cap": triplet(audit["new_cap"]),
        "reported_equity_ratio": triplet(audit["reported_equity_ratio"]),
        "legacy_sum_beta": triplet(audit["legacy_sum_beta"]),
        "new_sum_beta": triplet(audit["new_sum_beta"]),
        "legacy_cap_binding_ratio": float(audit["cap_binding_legacy"].mean()),
        "new_cap_binding_ratio": float(audit["cap_binding_new"].mean()),
        "top5_consistency": top5_consistency,
        "weekly_positions_max_abs_diff": max_abs_diff,
        "q1_q3_anomaly_reduced": q_anomaly_reduced,
        "material_model_change": top5_consistency < 0.95,
        "new_cap_basis_counts": audit["new_cap_basis"].value_counts().to_dict(),
    }

    document = [
        "# Phase B2 Equity Cap Comparison",
        "",
        "- Scope: only the equity-cap source/timing changed; no calibration was run.",
        "- Allocation availability: local files have no actual announcement-date field, so `period_end + 30 calendar days` is used conservatively.",
        "- Holdings availability remains `UNVERIFIED_PHASE_B3`; partial/TOP-N holdings never set a cap.",
        "",
        "## Aggregate comparison",
        "",
        "| Metric | Legacy | Disclosure |",
        "|---|---:|---:|",
        f"| Cap (min / median / max) | {pct_triplet(audit['legacy_cap'])} | {pct_triplet(audit['new_cap'])} |",
        f"| Σβ (min / median / max) | {pct_triplet(audit['legacy_sum_beta'])} | {pct_triplet(audit['new_sum_beta'])} |",
        f"| Cap binding ratio | {metrics['legacy_cap_binding_ratio']:.2%} | {metrics['new_cap_binding_ratio']:.2%} |",
        f"| Reported equity ratio (min / median / max) | — | {pct_triplet(audit['reported_equity_ratio'])} |",
        "",
        "## Quarterly timing check",
        "",
        "| Q1/Q3 period | Alloc available | Legacy cap median | New cap median | Legacy Σβ median | New Σβ median |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in q_windows.itertuples(index=False):
        document.append(
            f"| {row.period_end} | {row.available_date} | {row.legacy_cap_median:.2%} | "
            f"{row.new_cap_median:.2%} | {row.legacy_sum_beta_median:.2%} | {row.new_sum_beta_median:.2%} |"
        )
    document.extend([
        "",
        f"- Q1/Q3 low-cap anomaly materially reduced: **{'YES' if q_anomaly_reduced else 'NO'}**.",
        f"- Top-5 industry set consistency: **{top5_consistency:.2%}**; weekly position max absolute difference: **{max_abs_diff:.6f}**.",
        f"- Model-change gate: **{'MATERIAL_MODEL_CHANGE' if metrics['material_model_change'] else 'PASS'}**.",
        f"- Disclosure cap sources: `{json.dumps(metrics['new_cap_basis_counts'], ensure_ascii=False)}`.",
        "",
        "The disclosure cap is an upper bound, not a forced equality to the reported equity ratio.",
    ])
    doc_path = ROOT / "docs" / "development" / "PhaseB2_equity_cap_comparison.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("\n".join(document) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("code", nargs="?", default="161005")
    args = parser.parse_args()
    main(args.code)
