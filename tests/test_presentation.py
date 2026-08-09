import json

import numpy as np
import pandas as pd
import pytest

from api.presentation import build_presentation


def write_outputs(root, code="161005"):
    out = root / code
    out.mkdir(parents=True)
    dates = pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-30"])
    weekly = pd.DataFrame({
        "date": dates,
        "电子": [0.10, 0.12, 0.14, 0.20],
        "食品饮料": [0.20, 0.18, np.nan, 0.15],
        "通信": [0.05, 0.06, 0.07, 0.09],
    })
    weekly.to_csv(out / "weekly_positions.csv", index=False)
    pd.DataFrame({
        "date": dates,
        "r2": [0.8, 0.82, 0.84, 0.86],
        "sum_beta": [0.35, 0.36, 0.37, 0.44],
        "converged": [True] * 4,
        "n_obs": [120] * 4,
        "n_active": [3] * 4,
    }).to_csv(out / "diagnostics.csv", index=False)
    pd.DataFrame({
        "date": ["2025-12-31"], "电子": [0.11], "食品饮料": [0.21], "通信": [0.04]
    }).to_csv(out / "sim_portfolio.csv", index=False)
    (out / "report.md").write_text("# deterministic report", encoding="utf-8")
    return out


def test_presentation_top10_four_week_delta_sum_beta_and_trend(tmp_path):
    write_outputs(tmp_path)
    payload = build_presentation("161005", tmp_path, analysis_time=15.2)
    assert payload["top_industries"][0] == {"industry": "电子", "exposure": 0.2}
    assert payload["summary"]["implicit_exposure_sum"] == 0.44
    assert payload["summary"]["largest_increase"]["industry"] == "电子"
    assert payload["summary"]["largest_increase"]["delta"] == pytest.approx(0.10)
    assert payload["four_week_changes"]["from_date"] == "2026-01-02"
    assert len(payload["trend"]) == 4
    assert payload["disclosure_comparison"]
    assert payload["analysis_time"] == 15.2


def test_presentation_rejects_invalid_or_missing_output(tmp_path):
    with pytest.raises(ValueError):
        build_presentation("161005;rm", tmp_path)
    with pytest.raises(FileNotFoundError):
        build_presentation("161005", tmp_path)


def test_presentation_contains_no_nan(tmp_path):
    write_outputs(tmp_path)
    payload = build_presentation("161005", tmp_path)
    json.dumps(payload, allow_nan=False, ensure_ascii=False)
