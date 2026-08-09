import hashlib
import json
from pathlib import Path

from tools.check_locked_environment import check_environment, read_lock
from tools.check_production_regression import compare_weekly


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "tests" / "baseline" / "v4_a2_1_production"


def test_production_baseline_manifest_and_hash_are_stable():
    manifest = json.loads((PRODUCTION / "manifest.json").read_text(encoding="utf-8"))
    weekly = PRODUCTION / "weekly_positions.csv"
    assert manifest["model"] == "v4-a2.1-stable"
    assert manifest["files"]["weekly_positions.csv"]["industry_column_count"] == 27
    assert hashlib.sha256(weekly.read_bytes()).hexdigest() == manifest["files"]["weekly_positions.csv"]["sha256"]


def test_fixture_regression_comparison_is_exact():
    result = compare_weekly(
        PRODUCTION / "weekly_positions.csv", PRODUCTION / "weekly_positions.csv"
    )
    assert result["columns_equal"] is True
    assert result["max_abs_diff"] == 0.0
    assert result["top5_matches"] == result["rows"] == 1044
    assert result["has_coal"] is False


def test_pandas_2_fresh_evidence_detects_the_coal_drift():
    result = compare_weekly(
        ROOT / "tests" / "baseline" / "ui_v1_fresh" / "weekly_positions.csv",
        PRODUCTION / "weekly_positions.csv",
    )
    assert result["columns_equal"] is False
    assert result["extra_columns"] == ["煤炭"]
    assert result["max_abs_diff"] > 0.07
    assert result["top5_matches"] < result["rows"]


def test_dependency_lock_is_parseable_and_matches_verified_environment():
    lock_path = ROOT / "requirements-lock.txt"
    pins = read_lock(lock_path)
    assert pins["numpy"] == "2.5.1"
    assert pins["pandas"] == "3.0.5"
    result = check_environment(lock_path)
    assert result["verified"] is True
