import json

import numpy as np
import pandas as pd

from lib.calibrate import _ts_cv_split, score_params
from lib.calibrate_phase_a import (
    build_score_target_dates,
    fold_scores_from_error_matrix,
    run_phase_a_grid,
    score_errors_by_period,
)
from lib.regress import rolling_positions


def synthetic_inputs(seed=20260809):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=760)
    columns = [f"industry_{index}" for index in range(6)]
    factors = pd.DataFrame(rng.normal(0, 0.009, (len(dates), len(columns))), index=dates, columns=columns)
    beta = np.array([0.22, 0.18, 0.15, 0.12, 0.08, 0.05])
    fund = pd.Series(factors.to_numpy() @ beta + rng.normal(0, 0.001, len(dates)), index=dates)
    periods = pd.DatetimeIndex([
        pd.Timestamp("2022-06-30"), pd.Timestamp("2022-12-30"),
        pd.Timestamp("2023-06-30"), pd.Timestamp("2023-12-29"),
        pd.Timestamp("2024-06-28"), pd.Timestamp("2024-12-30"),
    ])
    sim = pd.DataFrame([beta] * len(periods), index=periods, columns=columns)
    return fund, factors, sim, periods, columns


def real_holdings(periods, columns):
    rows = []
    mapping = {}
    for index, industry in enumerate(columns):
        code = f"{index + 1:06d}"
        mapping[code] = industry
        for period in periods:
            rows.append({"code": code, "pct": 0.8 / len(columns), "period": period})
    return pd.DataFrame(rows), mapping


def test_target_dates_match_full_history_on_random_30_dates():
    fund, factors, sim, _, _ = synthetic_inputs()
    full_weights, full_diag = rolling_positions(
        fund, factors, sim_mat=sim, window=120, half_life=40,
        alpha=1e-6, equity_cap="auto", anchor_mult=None, verbose=False,
    )
    rng = np.random.default_rng(42)
    chosen = pd.DatetimeIndex(sorted(rng.choice(full_weights.index, size=30, replace=False)))
    target_weights, target_diag = rolling_positions(
        fund, factors, sim_mat=sim, window=120, half_life=40,
        alpha=1e-6, equity_cap="auto", anchor_mult=None, verbose=False,
        target_dates=chosen,
    )
    expected_weights = full_weights.loc[chosen]
    expected_diag = full_diag.loc[chosen]
    assert np.array_equal(target_weights.to_numpy(), expected_weights.to_numpy(), equal_nan=True)
    assert target_diag.equals(expected_diag)


def test_error_matrix_fold_scores_match_legacy_scoring():
    fund, factors, sim, periods, columns = synthetic_inputs()
    truth = pd.DataFrame([[0.8 / len(columns)] * len(columns)] * len(periods), index=periods, columns=columns)
    folds = _ts_cv_split(list(periods), 3)
    targets = build_score_target_dates(fund, factors, periods)
    combos = [
        (60, 0, 0.0, None),
        (90, 20, 1e-7, 2.5),
        (120, 40, 1e-6, None),
        (180, 80, 1e-5, 2.5),
    ]
    rows = {}
    legacy = {}
    for index, (window, half_life, alpha, anchor) in enumerate(combos):
        weights, _ = rolling_positions(
            fund, factors, sim_mat=sim, window=window, half_life=half_life,
            alpha=alpha, equity_cap="auto", anchor_mult=anchor, verbose=False,
            target_dates=targets,
        )
        errors, _ = score_errors_by_period(weights, truth)
        name = f"combo_{index}"
        rows[name] = errors
        legacy[name] = []
        for _, test_periods in folds:
            cutoff = max(test_periods) + pd.Timedelta(days=14)
            score = score_params(weights.loc[weights.index <= cutoff], truth.loc[test_periods])
            legacy[name].append(score["mae"])
    matrix = pd.DataFrame(rows).T
    phase_a = fold_scores_from_error_matrix(matrix, folds)
    for name in legacy:
        assert np.max(np.abs(np.asarray(legacy[name]) - np.asarray(phase_a[name]))) <= 1e-12


def test_checkpoint_resume_only_runs_missing_combos(tmp_path):
    fund, factors, sim, periods, columns = synthetic_inputs()
    holdings, mapping = real_holdings(periods, columns)
    common = dict(
        fund_ret=fund,
        factor_ret=factors,
        sim_mat=sim,
        real_holdings=holdings,
        stock2sw=mapping,
        output_dir=tmp_path,
        fund_code="161005",
        base_identity={"factor_source": "synthetic", "nav_hash": "n", "holdings_hash": "h", "base_hash": "b"},
        windows=(60, 90),
        half_lives=(0,),
        alphas=(0.0,),
        anchor_mults=(None, 2.5),
        max_calibration_seconds=300,
        safe_stop_seconds=285,
        verbose=False,
    )
    first = run_phase_a_grid(**common, combo_limit=2)
    assert first["status"] == "INTERRUPTED_TEST"
    assert first["completed_combos"] == 2
    second = run_phase_a_grid(**common)
    assert second["status"] == "COMPLETED"
    assert second["completed_combos"] == 4
    checkpoint = pd.read_csv(tmp_path / "calibration_checkpoint.csv")
    assert checkpoint["combo_id"].nunique() == 4
    assert len(checkpoint) == 4
    assert pd.read_csv(tmp_path / "error_matrix.csv", index_col=0).shape == (4, len(periods))
    meta = json.loads((tmp_path / "calibration_meta.json").read_text(encoding="utf-8"))
    assert meta["resumed"] is True
    candidate = json.loads((tmp_path / "best_params_phaseA_candidate.json").read_text(encoding="utf-8"))
    assert candidate["production_eligible"] is False
