import numpy as np
import pandas as pd
from scipy.optimize import minimize

from lib.regress import (
    _latest_sim_row,
    disclosure_align,
    index_to_returns,
    nav_to_returns,
)
from lib.simulate import SimulatedPortfolio
from lib.solver import exp_decay_weights, project_box_simplex, solve_weighted_lasso
from run_analysis import load_base, load_fund


def _scipy_reference(X, y, w, alpha, max_sum, caps):
    weights = np.asarray(w, dtype=float)
    weights /= weights.sum()
    xbar = (weights[:, None] * X).sum(axis=0)
    ybar = float((weights * y).sum())
    centered_x = X - xbar
    centered_y = y - ybar
    A = centered_x.T @ (weights[:, None] * centered_x)
    b = (weights[:, None] * centered_x).T @ centered_y
    scale = 1e5

    def objective(beta):
        return scale * (beta @ A @ beta - 2.0 * b @ beta + alpha * beta.sum())

    def jacobian(beta):
        return scale * (2.0 * (A @ beta - b) + alpha)

    if caps is None:
        bounds = [(0.0, None)] * X.shape[1]
    else:
        bounds = [(0.0, float(cap)) for cap in caps]
    result = minimize(
        objective,
        np.zeros(X.shape[1]),
        jac=jacobian,
        bounds=bounds,
        constraints={
            "type": "ineq",
            "fun": lambda beta: max_sum - beta.sum(),
            "jac": lambda beta: -np.ones_like(beta),
        },
        method="SLSQP",
        options={"ftol": 1e-12, "maxiter": 2000},
    )
    assert result.success, result.message
    return result.x, objective


def test_box_simplex_projection_constraints():
    rng = np.random.default_rng(20260809)
    for _ in range(200):
        values = rng.normal(size=31)
        caps = rng.uniform(0.01, 0.30, size=31)
        budget = rng.uniform(0.2, 0.98)
        projected = project_box_simplex(values, budget, caps)
        assert projected.min() >= -1e-12
        assert np.all(projected <= caps + 1e-9)
        assert projected.sum() <= budget + 1e-9


def test_100_real_solver_samples_against_scipy_reference():
    index_long, stock2sw = load_base()
    nav, holdings, allocation = load_fund("161005")
    portfolio = SimulatedPortfolio(holdings, allocation, stock2sw, verbose=False)
    sim_mat, _ = portfolio.build_all()
    sim_disc = disclosure_align(sim_mat)
    fund_ret, _ = nav_to_returns(nav)
    factor_ret = index_to_returns(index_long)
    dates = fund_ret.index.intersection(factor_ret.index)
    factors = factor_ret.reindex(dates).fillna(0.0)
    response = fund_ret.reindex(dates)
    columns = list(factors.columns)
    rebalance = pd.Series(1, index=dates).resample("W-FRI").last().dropna().index[-100:]
    grids = [(60, 0), (90, 20), (120, 40), (180, 80), (250, 40)]
    alphas = (0.0, 1e-7, 1e-6, 1e-5)

    max_difference = 0.0
    worst = None
    for sample_index, date in enumerate(rebalance):
        window, half_life = grids[sample_index % len(grids)]
        history = dates[dates <= date][-window:]
        X = factors.reindex(history).values
        y = response.reindex(history).values
        weights = exp_decay_weights(len(y), half_life)
        prior = _latest_sim_row(sim_disc, date)
        max_sum = min(float(prior.sum()) * 1.05, 0.98) if prior is not None else 0.95
        caps = None
        if sample_index % 2 and prior is not None:
            caps = np.array([2.5 * float(prior.get(column, 0.0)) + 0.03 for column in columns])
        alpha = alphas[sample_index % len(alphas)]

        production = solve_weighted_lasso(
            X, y, w=weights, alpha=alpha, max_sum=max_sum, cap_vec=caps
        )
        reference_beta, objective = _scipy_reference(
            X, y, weights, alpha, max_sum, caps
        )
        difference = float(np.max(np.abs(production["beta"] - reference_beta)))
        if difference > max_difference:
            max_difference = difference
            worst = (sample_index, production["n_iter"], production["kkt_residual"])
        assert production["beta"].min() >= -1e-12
        if caps is not None:
            assert np.all(production["beta"] <= caps + 1e-9)
        assert production["beta"].sum() <= max_sum + 1e-9
        assert objective(production["beta"]) <= objective(reference_beta) + 1e-8

    assert max_difference <= 1e-6, (max_difference, worst)
