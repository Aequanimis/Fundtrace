#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose the B2 equity-cap material model change without rerunning a model."""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _read_csv(path_or_buffer):
    return pd.read_csv(path_or_buffer)


def _read_zip_entry(archive: Path, suffix: str, code: str):
    expected = f"/output/{code}/{suffix}"
    with zipfile.ZipFile(archive) as zf:
        entries = [entry for entry in zf.namelist() if entry.endswith(expected)]
        if len(entries) != 1:
            raise FileNotFoundError(f"Expected one {expected} in {archive}, found {entries}")
        return zf.read(entries[0])


def _legacy_artifact(code: str, name: str):
    archive = ROOT.parent / "FundTrace_V4_PhaseB0_B1_验收包.zip"
    if not archive.exists():
        raise FileNotFoundError(f"Missing frozen B1 archive: {archive}")
    return _read_zip_entry(archive, name, code)


def _legacy_csv(code: str, name: str):
    return _read_csv(io.BytesIO(_legacy_artifact(code, name)))


def _as_bool(values):
    if isinstance(values, pd.Series):
        return values.astype(str).str.strip().str.lower().isin(("true", "1", "yes"))
    return str(values).strip().lower() in {"true", "1", "yes"}


def _quarter(value):
    date = pd.to_datetime(value, errors="coerce")
    if pd.isna(date):
        return ""
    return {
        (3, 31): "Q1", (6, 30): "INTERIM", (9, 30): "Q3", (12, 31): "ANNUAL",
    }.get((date.month, date.day), "")


def _top5(frame):
    return " | ".join(frame.nlargest(5).index.tolist())


def _load_weekly(path):
    frame = pd.read_csv(path)
    date_col = "date" if "date" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={date_col: "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def _output_text_from_b1(code: str, name: str):
    return _legacy_artifact(code, name).decode("utf-8-sig")


def _input_audit(code: str):
    """Statically verify that the only run-path difference is the cap source."""
    source = (ROOT / "lib" / "regress.py").read_text(encoding="utf-8")
    report_old = _output_text_from_b1(code, "report.md")
    report_new = (ROOT / "output" / code / "report.md").read_text(encoding="utf-8")
    parameter_labels = ("回归窗口", "时间权重半衰期", "Lasso 强度 alpha", "逐行业锚定倍数")
    params_same = all(
        next((line for line in report_old.splitlines() if label in line), "")
        == next((line for line in report_new.splitlines() if label in line), "")
        for label in parameter_labels
    )
    prior_at = source.find("prior = _latest_sim_row")
    branch_at = source.find("if equity_cap_mode == \"disclosure\":")
    cap_vec_at = source.find("# 逐行业 β 上界锚定")
    solve_at = source.find("res = _solve_with_caps")
    branch_is_cap_only = 0 <= prior_at < branch_at < cap_vec_at < solve_at
    sim_old = _legacy_artifact(code, "sim_portfolio.csv")
    sim_new = (ROOT / "output" / code / "sim_portfolio.csv").read_bytes()
    sim_same = sim_old == sim_new
    status = "INPUTS_CONFIRMED_IDENTICAL" if params_same and branch_is_cap_only and sim_same else "UNEXPECTED_INPUT_CHANGE"
    return {
        "status": status,
        "window_half_life_alpha_anchor_same": params_same,
        "x_y_and_prior_created_before_cap_branch": branch_is_cap_only,
        "simulated_portfolio_same": sim_same,
        "disclosure_row_selection_change": "EXPECTED_CAP_SOURCE_CHANGE",
    }


def _format_pct(value):
    return "n/a" if pd.isna(value) else f"{float(value):.2%}"


def _format_table(frame, columns, formats):
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in frame.itertuples(index=False):
        values = []
        for col in columns:
            value = getattr(row, col)
            values.append(formats.get(col, str)(value) if col in formats else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def main(code="161005"):
    code = str(code).zfill(6)
    outdir = ROOT / "output" / code
    baseline = ROOT / "tests" / "baseline"
    legacy_weekly = _load_weekly(baseline / "phaseB2_legacy_weekly_positions.csv")
    new_weekly = _load_weekly(outdir / "weekly_positions.csv")
    legacy_diag = _legacy_csv(code, "diagnostics.csv")
    new_diag = pd.read_csv(outdir / "diagnostics.csv")
    cap_baseline = pd.read_csv(baseline / "phaseB2_legacy_equity_cap.csv")
    audit = pd.read_csv(outdir / "equity_cap_audit.csv")

    for frame in (legacy_diag, new_diag, cap_baseline, audit):
        frame["date"] = pd.to_datetime(frame["date"])
    if not legacy_weekly.index.equals(new_weekly.index):
        raise ValueError("Legacy/new weekly dates do not match")
    if len(audit) != 1044 or len(legacy_diag) != 1044 or len(new_diag) != 1044:
        raise ValueError("Expected 1044 weekly diagnostic rows in each input")

    common_cols = legacy_weekly.columns.intersection(new_weekly.columns)
    legacy_values = legacy_weekly[common_cols].apply(pd.to_numeric, errors="coerce")
    new_values = new_weekly[common_cols].apply(pd.to_numeric, errors="coerce")
    abs_diffs = (legacy_values - new_values).abs()
    max_diff_industry = abs_diffs.idxmax(axis=1)
    max_abs_diff = abs_diffs.max(axis=1)
    dates = legacy_weekly.index
    weekly = pd.DataFrame({
        "date": dates,
        "legacy_top5": [_top5(legacy_values.loc[date]) for date in dates],
        "new_top5": [_top5(new_values.loc[date]) for date in dates],
        "top5_same": [
            set(legacy_values.loc[date].nlargest(5).index)
            == set(new_values.loc[date].nlargest(5).index)
            for date in dates
        ],
        "max_industry_abs_diff": max_abs_diff.to_numpy(),
        "max_diff_industry": max_diff_industry.to_numpy(),
    })
    weekly["legacy_max_diff_industry_weight"] = [
        float(legacy_values.loc[date, industry])
        for date, industry in zip(dates, weekly["max_diff_industry"])
    ]
    weekly["new_max_diff_industry_weight"] = [
        float(new_values.loc[date, industry])
        for date, industry in zip(dates, weekly["max_diff_industry"])
    ]

    legacy_diag = legacy_diag.rename(columns={
        "r2": "legacy_r2", "converged": "legacy_converged",
    })[["date", "legacy_r2", "legacy_converged"]]
    new_diag = new_diag.rename(columns={
        "r2": "new_r2", "converged": "new_converged",
    })[["date", "new_r2", "new_converged"]]
    cap_baseline = cap_baseline.rename(columns={
        "sum_beta": "legacy_sum_beta", "latest_prior_period": "legacy_source_period",
    })[["date", "legacy_sum_beta", "legacy_cap", "legacy_source_period"]]
    audit = audit.rename(columns={
        "new_cap_source_period": "new_cap_source_period",
        "reported_equity_ratio": "new_reported_equity_ratio",
        "new_sum_beta": "new_sum_beta",
        "cap_binding_legacy": "legacy_cap_binding",
        "cap_binding_new": "new_cap_binding",
    })[[
        "date", "new_cap", "new_cap_source_period", "new_reported_equity_ratio",
        "new_sum_beta", "legacy_cap_binding", "new_cap_binding",
    ]]
    diagnostic = weekly.merge(cap_baseline, on="date", validate="one_to_one")
    diagnostic = diagnostic.merge(audit, on="date", validate="one_to_one")
    diagnostic = diagnostic.merge(legacy_diag, on="date", validate="one_to_one")
    diagnostic = diagnostic.merge(new_diag, on="date", validate="one_to_one")
    diagnostic["legacy_cap_binding"] = _as_bool(diagnostic["legacy_cap_binding"])
    diagnostic["new_cap_binding"] = _as_bool(diagnostic["new_cap_binding"])
    diagnostic["legacy_converged"] = _as_bool(diagnostic["legacy_converged"])
    diagnostic["new_converged"] = _as_bool(diagnostic["new_converged"])
    diagnostic["cap_change"] = diagnostic["new_cap"] - diagnostic["legacy_cap"]
    diagnostic["sum_beta_change"] = diagnostic["new_sum_beta"] - diagnostic["legacy_sum_beta"]
    diagnostic["report_quarter"] = diagnostic["new_cap_source_period"].map(_quarter)
    diagnostic.loc[diagnostic["report_quarter"].eq(""), "report_quarter"] = diagnostic.loc[
        diagnostic["report_quarter"].eq(""), "legacy_source_period"
    ].map(_quarter)
    released = diagnostic["legacy_cap_binding"] & (diagnostic["cap_change"] > 0.03)
    diagnostic["classification"] = np.select(
        [
            released & (diagnostic["sum_beta_change"] > 0.02),
            released & (diagnostic["sum_beta_change"].abs() <= 0.02),
            ~diagnostic["legacy_cap_binding"] & (
                (diagnostic["max_industry_abs_diff"] > 0.02) | ~diagnostic["top5_same"]
            ),
        ],
        ["TYPE_A_CAP_RELEASED", "TYPE_B_CAP_RELEASED_BUT_BETA_LOW", "TYPE_C_NON_BINDING_CHANGED"],
        default="TYPE_D_MINOR",
    )
    diagnostic = diagnostic[[
        "date", "legacy_cap", "new_cap", "cap_change", "legacy_sum_beta", "new_sum_beta",
        "sum_beta_change", "legacy_cap_binding", "new_cap_binding", "legacy_r2", "new_r2",
        "legacy_converged", "new_converged", "legacy_top5", "new_top5", "top5_same",
        "max_industry_abs_diff", "max_diff_industry", "legacy_max_diff_industry_weight",
        "new_max_diff_industry_weight", "legacy_source_period", "new_cap_source_period",
        "report_quarter", "classification",
    ]].sort_values("date")
    diagnostic_path = outdir / "B2_material_change_diagnostic.csv"
    diagnostic.to_csv(diagnostic_path, index=False, encoding="utf-8-sig")

    top_changes = diagnostic.nlargest(20, "max_industry_abs_diff").copy()
    top_changes["industry"] = top_changes["max_diff_industry"]
    top_changes["legacy_weight"] = top_changes["legacy_max_diff_industry_weight"]
    top_changes["new_weight"] = top_changes["new_max_diff_industry_weight"]
    top_changes["difference"] = top_changes["new_weight"] - top_changes["legacy_weight"]
    top_changes["type"] = top_changes["classification"]
    top_changes = top_changes[[
        "date", "industry", "legacy_weight", "new_weight", "difference", "legacy_cap", "new_cap",
        "legacy_sum_beta", "new_sum_beta", "legacy_cap_binding", "new_cap_binding", "legacy_r2",
        "new_r2", "type",
    ]]
    top_changes.to_csv(outdir / "B2_material_change_top20.csv", index=False, encoding="utf-8-sig")

    legacy_low = diagnostic.nsmallest(20, "legacy_sum_beta")
    new_low = diagnostic.nsmallest(20, "new_sum_beta")
    legacy_low.to_csv(outdir / "B2_low_sum_beta_legacy_top20.csv", index=False, encoding="utf-8-sig")
    new_low.to_csv(outdir / "B2_low_sum_beta_new_top20.csv", index=False, encoding="utf-8-sig")

    counts = diagnostic["classification"].value_counts().reindex([
        "TYPE_A_CAP_RELEASED", "TYPE_B_CAP_RELEASED_BUT_BETA_LOW",
        "TYPE_C_NON_BINDING_CHANGED", "TYPE_D_MINOR",
    ], fill_value=0)
    top5_changes = diagnostic.loc[~diagnostic["top5_same"]].copy()
    top5_type_counts = top5_changes["classification"].value_counts().to_dict()
    r2_bands = pd.cut(
        diagnostic["legacy_r2"], bins=[-np.inf, 0.3, 0.6, np.inf],
        labels=["<0.3", "0.3-0.6", ">0.6"], right=False,
    )
    r2_change_rates = pd.DataFrame({"band": r2_bands, "top5_changed": ~diagnostic["top5_same"]}).groupby(
        "band", observed=False
    )["top5_changed"].agg(["count", "mean"])
    input_audit = _input_audit(code)
    type_c = int(counts["TYPE_C_NON_BINDING_CHANGED"])
    if type_c > 0 and input_audit["status"] == "UNEXPECTED_INPUT_CHANGE":
        conclusion = "B2_IMPLEMENTATION_BUG_SUSPECTED"
    elif type_c <= max(3, int(0.01 * len(diagnostic))) and top5_type_counts.get("TYPE_A_CAP_RELEASED", 0) >= top5_type_counts.get("TYPE_C_NON_BINDING_CHANGED", 0):
        conclusion = "B2_CHANGE_MOSTLY_EXPLAINED_BY_CAP_RELEASE"
    else:
        conclusion = "MODEL_UNDERIDENTIFICATION_SENSITIVITY"

    max_row = top_changes.iloc[0]
    legacy_min = legacy_low.iloc[0]
    new_min = new_low.iloc[0]
    top5_q13 = int(top5_changes["report_quarter"].isin(("Q1", "Q3")).sum())
    top5_low_cap = int((top5_changes["legacy_cap"] < 0.8).sum())
    low_beta_not_cap = diagnostic.loc[
        diagnostic["legacy_sum_beta"] < diagnostic["legacy_cap"] - 0.02
    ]
    released_share = int(counts["TYPE_A_CAP_RELEASED"] + counts["TYPE_B_CAP_RELEASED_BUT_BETA_LOW"])
    summary = {
        "classification_counts": {key: int(value) for key, value in counts.items()},
        "classification_shares": {key: float(value / len(diagnostic)) for key, value in counts.items()},
        "top5_change_count": int(len(top5_changes)),
        "top5_change_first": top5_changes["date"].min().strftime("%Y-%m-%d") if len(top5_changes) else None,
        "top5_change_last": top5_changes["date"].max().strftime("%Y-%m-%d") if len(top5_changes) else None,
        "top5_change_q1_q3_count": top5_q13,
        "top5_change_legacy_cap_lt_80_count": top5_low_cap,
        "top5_change_type_counts": {key: int(value) for key, value in top5_type_counts.items()},
        "max_change": {
            "date": max_row["date"].strftime("%Y-%m-%d"), "industry": max_row["industry"],
            "difference": float(max_row["difference"]), "type": max_row["type"],
            "legacy_cap_binding": bool(max_row["legacy_cap_binding"]),
        },
        "legacy_lowest": {"date": legacy_min["date"].strftime("%Y-%m-%d"), "sum_beta": float(legacy_min["legacy_sum_beta"]), "cap_binding": bool(legacy_min["legacy_cap_binding"])},
        "new_lowest": {"date": new_min["date"].strftime("%Y-%m-%d"), "sum_beta": float(new_min["new_sum_beta"]), "cap_binding": bool(new_min["new_cap_binding"])},
        "legacy_low_not_directly_cap_count": int(len(low_beta_not_cap)),
        "input_audit": input_audit,
        "r2_change_rates": {
            str(index): {"count": int(row["count"]), "top5_change_rate": float(row["mean"])}
            for index, row in r2_change_rates.iterrows()
        },
        "conclusion": conclusion,
        "released_count": released_share,
        "released_share": float(released_share / len(diagnostic)),
    }

    year_counts = top5_changes.assign(year=top5_changes["date"].dt.year).groupby("year").size()
    report = [
        "# B2 Material Model Change Diagnostic",
        "",
        "Scope: static comparison of frozen B1 legacy artifacts and the existing B2 disclosure-cap output. No model or calibration rerun was performed.",
        "",
        "## Result",
        "",
        f"- Top-5 consistency is **{diagnostic['top5_same'].mean():.2%}** ({len(top5_changes)}/{len(diagnostic)} changed).",
        f"- Classification: A {counts.iloc[0]} ({counts.iloc[0] / len(diagnostic):.2%}), B {counts.iloc[1]} ({counts.iloc[1] / len(diagnostic):.2%}), C {counts.iloc[2]} ({counts.iloc[2] / len(diagnostic):.2%}), D {counts.iloc[3]} ({counts.iloc[3] / len(diagnostic):.2%}).",
        f"- The largest industry change is **{max_row['difference']:+.2%}** on {max_row['date']:%Y-%m-%d}: {max_row['industry']} ({max_row['legacy_weight']:.2%} → {max_row['new_weight']:.2%}); legacy cap binding={bool(max_row['legacy_cap_binding'])}; {max_row['type']}.",
        f"- Legacy cap actually released the fitted exposure in A/B for {released_share}/{len(diagnostic)} weeks ({released_share / len(diagnostic):.2%}).",
        f"- Legacy minimum Σβ is {legacy_min['legacy_sum_beta']:.2%} on {legacy_min['date']:%Y-%m-%d}; cap binding={bool(legacy_min['legacy_cap_binding'])}. New minimum is {new_min['new_sum_beta']:.2%} on {new_min['date']:%Y-%m-%d}; cap binding={bool(new_min['new_cap_binding'])}.",
        f"- {len(low_beta_not_cap)}/{len(diagnostic)} legacy weeks have Σβ < cap − 2pp: these low implied exposures are not directly caused by the legacy equity cap.",
        f"- Input audit: **{input_audit['status']}** (X/y/prior precede the cap branch, run parameters and simulated portfolio match; disclosure row selection is the intended cap-source change).",
        f"- R² relation: changed weeks legacy/new median R² = {top5_changes['legacy_r2'].median():.3f}/{top5_changes['new_r2'].median():.3f}; unchanged = {diagnostic.loc[diagnostic['top5_same'], 'legacy_r2'].median():.3f}/{diagnostic.loc[diagnostic['top5_same'], 'new_r2'].median():.3f}.",
        f"- Conclusion: **{conclusion}**.",
        "",
        "## Top-5 changes",
        "",
        f"- Range: {summary['top5_change_first']} to {summary['top5_change_last']}; Q1/Q3-source weeks {top5_q13}/{len(top5_changes)}; legacy cap <80% weeks {top5_low_cap}/{len(top5_changes)}.",
        f"- Types among changed weeks: `{json.dumps(summary['top5_change_type_counts'], ensure_ascii=False)}`.",
        f"- By year: `{json.dumps({str(year): int(year_counts.get(year, 0)) for year in range(2014, 2027)}, ensure_ascii=False)}`.",
        "",
        "## R² bands",
        "",
        "| Legacy R² band | Weeks | Top-5 change rate |",
        "|---|---:|---:|",
    ]
    for band, row in r2_change_rates.iterrows():
        report.append(f"| {band} | {int(row['count'])} | {float(row['mean']):.2%} |")
    report.extend([
        "",
        "## Top 20 one-industry differences",
        "",
    ])
    report.extend(_format_table(
        top_changes,
        ["date", "industry", "legacy_weight", "new_weight", "difference", "legacy_cap", "new_cap", "type"],
        {"date": lambda x: pd.Timestamp(x).strftime("%Y-%m-%d"),
         "legacy_weight": _format_pct, "new_weight": _format_pct, "difference": lambda x: f"{float(x):+.2%}",
         "legacy_cap": _format_pct, "new_cap": _format_pct},
    ))
    report.extend([
        "",
        "## Decision",
        "",
        "Do not continue B2 automatically while Top-5 consistency remains below 95%. Keep A2.1 legacy as the current MVP until the sensitivity is independently accepted or a later design narrows the change scope.",
    ])
    report_path = ROOT / "docs" / "development" / "B2_material_model_change_diagnostic.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("code", nargs="?", default="161005")
    main(parser.parse_args().code)
