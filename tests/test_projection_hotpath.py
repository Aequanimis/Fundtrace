import numpy as np
import lib.solver as solver

from lib.solver import (
    project_box_simplex,
    project_box_simplex_generic,
    project_capped_simplex,
)


def test_cap_none_fast_projection_matches_a2_generic_projection():
    rng = np.random.default_rng(20260810)
    dimensions = (5, 27, 31)
    budgets = (0.5, 0.8, 0.95, 1.0)
    max_abs_diff = 0.0
    for sample in range(500):
        size = dimensions[sample % len(dimensions)]
        budget = budgets[sample % len(budgets)]
        values = rng.normal(size=size)
        generic = project_box_simplex_generic(values, budget, cap=None)
        fast = project_capped_simplex(values, budget)
        routed = project_box_simplex(values, budget, cap=None)
        max_abs_diff = max(max_abs_diff, float(np.max(np.abs(generic - fast))))
        assert np.array_equal(fast, routed)
        assert fast.min() >= -1e-12
        assert fast.sum() <= budget + 1e-12
    assert max_abs_diff <= 1e-12


def test_anchor_none_solver_matches_high_precision_a2_generic_path(monkeypatch):
    from lib.calibrate import _real_industry_matrix
    from lib.calibrate_phase_a import build_score_target_dates
    from lib.regress import index_to_returns, nav_to_returns, rolling_positions
    from lib.simulate import SimulatedPortfolio
    from run_analysis import extract_real_holdings, load_base, load_fund

    index_long, stock2sw = load_base()
    nav, holdings, allocation = load_fund("161005")
    portfolio = SimulatedPortfolio(holdings, allocation, stock2sw, verbose=False)
    sim_mat, _ = portfolio.build_all()
    real_mat = _real_industry_matrix(extract_real_holdings(holdings, portfolio), stock2sw)
    fund_ret, _ = nav_to_returns(nav)
    factor_ret = index_to_returns(index_long)
    target_dates = build_score_target_dates(fund_ret, factor_ret, real_mat.index)
    combos = ((60, 0, 0.0), (120, 40, 1e-5), (250, 80, 1e-6))
    fast_results = []
    for window, half_life, alpha in combos:
        fast_results.append(rolling_positions(
            fund_ret, factor_ret, sim_mat=sim_mat, window=window,
            half_life=half_life, alpha=alpha, equity_cap="auto",
            anchor_mult=None, verbose=False, target_dates=target_dates,
        )[0])

    def high_precision_generic(v, B, cap=None, tol=1e-13, max_iter=100):
        return project_box_simplex_generic(v, B, cap=cap, tol=1e-15, max_iter=max_iter)

    monkeypatch.setattr(solver, "project_box_simplex", high_precision_generic)
    max_abs_diff = 0.0
    for (window, half_life, alpha), expected in zip(combos, fast_results):
        generic, _ = rolling_positions(
            fund_ret, factor_ret, sim_mat=sim_mat, window=window,
            half_life=half_life, alpha=alpha, equity_cap="auto",
            anchor_mult=None, verbose=False, target_dates=target_dates,
        )
        max_abs_diff = max(max_abs_diff, float(np.max(np.abs(
            generic.to_numpy() - expected.to_numpy()
        ))))
        for date in expected.index:
            assert set(generic.loc[date].nlargest(5).index) == set(expected.loc[date].nlargest(5).index)
    assert max_abs_diff <= 1e-10
