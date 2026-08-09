#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate local Phase B disclosure diagnostics without touching model inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.disclosure import build_disclosure_index  # noqa: E402


def topline_status(summary):
    valid = summary[summary["status"] == "OK"]
    if valid.empty:
        return "TOPLINE_TEST_UNAVAILABLE"
    by_period = valid.groupby("period_end")["rows"].apply(list)
    if any(max(values) > 100 for values in by_period):
        return "TOPLINE_TRUNCATION_CONFIRMED"
    if all(len(set(values)) == 1 and values[0] == 100 for values in by_period):
        return "TOPLINE_API_LIMIT"
    return "TOPLINE_RESPONSE_UNRELIABLE"


def main(code="161005"):
    code = str(code).zfill(6)
    fund_dir = ROOT / "funds" / code
    evidence_path = ROOT / "tests" / "evidence" / "topline_test" / "summary.csv"
    summary = pd.read_csv(evidence_path)
    status = topline_status(summary)
    index = build_disclosure_index(
        pd.read_csv(fund_dir / "holdings.csv"),
        pd.read_csv(fund_dir / "industry_alloc.csv"),
        topline_used=100,
        fund_code=code,
        holdings_source_status=status,
    )
    index.to_csv(fund_dir / "disclosure_index.csv", index=False, encoding="utf-8-sig")
    ratios = pd.to_numeric(index["coverage_ratio"], errors="coerce").dropna()
    by_period = {}
    for period, group in summary.groupby("period_end"):
        by_period[str(period)] = {
            str(int(row.topline)): {
                "status": row.status,
                "rows": int(row.rows) if pd.notna(row.rows) else None,
                "http_success": bool(row.http_success),
                "has_rows_after_100": bool(row.has_rows_after_100) if pd.notna(row.has_rows_after_100) else None,
            }
            for row in group.itertuples()
        }
    coverage_counts = {name: 0 for name in (
        "TOP10", "PARTIAL", "TOP_N_TRUNCATED", "FULL_CONFIRMED", "UNKNOWN",
    )}
    coverage_counts.update({key: int(value) for key, value in index["coverage_type"].value_counts().to_dict().items()})
    audit = {
        "fund_code": code,
        "n_periods": int(len(index)),
        "topline_test_status": status,
        "topline_test": by_period,
        "coverage_counts": coverage_counts,
        "median_coverage_ratio": float(ratios.median()) if len(ratios) else None,
        "min_coverage_ratio": float(ratios.min()) if len(ratios) else None,
        "max_coverage_ratio": float(ratios.max()) if len(ratios) else None,
        "source_unverified_count": int(index["flags"].str.contains("SOURCE_UNVERIFIED", na=False).sum()),
    }
    output_dir = ROOT / "output" / code
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "disclosure_audit_summary.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(index.to_string(index=False))
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "161005")
