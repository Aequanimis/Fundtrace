import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from lib.disclosure import build_disclosure_index, resolve_equity_cap
from lib.equity_cap_audit import AUDIT_COLUMNS, build_equity_cap_audit
from lib.regress import index_to_returns, nav_to_returns, rolling_positions
from lib.simulate import SimulatedPortfolio
from run_analysis import load_base, load_fund


def alloc_row(period, ratio, available, *, coverage_type="PARTIAL", holdings_sum=0.20,
              cap_eligible=True, holdings_available=""):
    return {
        "period_end": period,
        "reported_equity_ratio": ratio,
        "alloc_available_date": available,
        "alloc_source_status": "AVAILABLE",
        "cap_eligible": cap_eligible,
        "coverage_type": coverage_type,
        "holdings_sum": holdings_sum,
        "holdings_available_date": holdings_available,
    }


def test_alloc_available_date_is_30_calendar_day_fallback_and_independent_of_report_type():
    holdings = pd.DataFrame({
        "period_end": ["2024-06-30"],
        "stock_code": ["000001"],
        "holding_pct": [20],
    })
    allocation = pd.DataFrame({
        "period_end": ["2024-06-30"],
        "allocation_pct": [95],
    })
    row = build_disclosure_index(holdings, allocation).iloc[0]
    assert row["report_type"] == "INTERIM"
    assert row["alloc_available_date"] == "2024-07-30"
    assert row["alloc_available_date_status"] == "CONSERVATIVE_30D_FALLBACK"
    assert row["holdings_available_date"] == ""
    assert row["holdings_available_date_status"] == "UNVERIFIED_PHASE_B3"
    assert row["cap_eligible"]


def test_actual_local_announcement_field_takes_priority_when_present():
    holdings = pd.DataFrame({
        "period_end": ["2024-03-31"],
        "stock_code": ["000001"],
        "holding_pct": [20],
    })
    allocation = pd.DataFrame({
        "period_end": ["2024-03-31"],
        "allocation_pct": [90],
        "announcement_date": ["2024-04-25"],
    })
    row = build_disclosure_index(holdings, allocation).iloc[0]
    assert row["alloc_available_date"] == "2024-04-25"
    assert row["alloc_available_date_status"] == "ACTUAL_SOURCE_DATE"
    assert row["alloc_available_date_source"] == "announcement_date"


def test_q1_to_q4_allocations_never_look_ahead_and_switch_on_available_date():
    frame = pd.DataFrame([
        alloc_row("2024-12-31", 0.80, "2025-01-30"),
        alloc_row("2025-03-31", 0.81, "2025-04-30"),
        alloc_row("2025-06-30", 0.82, "2025-07-30"),
        alloc_row("2025-09-30", 0.83, "2025-10-30"),
        alloc_row("2025-12-31", 0.84, "2026-01-30"),
    ])
    periods = [
        ("2025-03-31", "2025-04-29", "2024-12-31"),
        ("2025-06-30", "2025-07-29", "2025-03-31"),
        ("2025-09-30", "2025-10-29", "2025-06-30"),
        ("2025-12-31", "2026-01-29", "2025-09-30"),
    ]
    for current_period, before_available, expected_prior in periods:
        before = resolve_equity_cap(frame, before_available)
        on_date = resolve_equity_cap(
            frame, pd.Timestamp(current_period) + pd.Timedelta(days=30)
        )
        assert before["source_period"] == expected_prior
        assert on_date["source_period"] == current_period
        assert on_date["cap_basis"] == "INDUSTRY_ALLOC"


def test_constant_fallback_has_no_nan_cap_or_future_source():
    result = resolve_equity_cap(pd.DataFrame(), "2025-04-29")
    assert result["cap_basis"] == "CONSTANT_FALLBACK"
    assert result["flags"] == "NO_VISIBLE_ALLOC"
    assert result["cap_value"] == 0.95
    assert np.isfinite(result["cap_value"])
    assert result["source_period"] is None


def test_partial_and_top_n_holdings_never_become_cap_fallbacks():
    frame = pd.DataFrame([
        alloc_row("2024-03-31", np.nan, "", coverage_type="PARTIAL", holdings_sum=0.20,
                  cap_eligible=False, holdings_available="2024-05-01"),
        alloc_row("2024-06-30", np.nan, "", coverage_type="TOP_N_TRUNCATED", holdings_sum=0.90,
                  cap_eligible=False, holdings_available="2024-08-01"),
    ])
    result = resolve_equity_cap(frame, "2024-12-31")
    assert result["cap_basis"] == "CONSTANT_FALLBACK"
    assert result["cap_value"] == 0.95


def test_visible_full_confirmed_holdings_is_the_only_holdings_fallback():
    frame = pd.DataFrame([
        alloc_row("2024-12-31", np.nan, "", coverage_type="FULL_CONFIRMED", holdings_sum=0.80,
                  cap_eligible=False, holdings_available="2025-02-01"),
    ])
    result = resolve_equity_cap(frame, "2025-02-01")
    assert result["cap_basis"] == "FULL_CONFIRMED_HOLDINGS"
    assert result["source_period"] == "2024-12-31"
    assert np.isclose(result["cap_value"], 0.84)
    assert np.isfinite(result["cap_value"])


def test_ratio_units_buffer_and_hard_max_are_correct():
    frame = pd.DataFrame([
        alloc_row("2025-03-31", 0.80, "2025-04-30"),
        alloc_row("2025-06-30", 0.96, "2025-07-30"),
    ])
    regular = resolve_equity_cap(frame, "2025-04-30")
    capped = resolve_equity_cap(frame, "2025-07-30")
    assert regular["reported_equity_ratio"] == 0.80
    assert np.isclose(regular["cap_value"], 0.84)
    assert np.isclose(capped["cap_value"], 0.98)
    assert regular["cap_value"] <= 0.98 and capped["cap_value"] <= 0.98


def _synthetic_regression_inputs():
    rng = np.random.default_rng(20260812)
    dates = pd.bdate_range("2024-01-02", periods=180)
    factors = pd.DataFrame(
        rng.normal(0, 0.01, (len(dates), 3)), index=dates, columns=["a", "b", "c"]
    )
    fund = pd.Series(factors.to_numpy() @ np.array([0.30, 0.20, 0.15]), index=dates)
    sim = pd.DataFrame([[0.30, 0.20, 0.15]], index=[pd.Timestamp("2023-12-31")], columns=factors.columns)
    return fund, factors, sim


def test_legacy_mode_matches_the_pre_b2_default_path():
    fund, factors, sim = _synthetic_regression_inputs()
    default_w, default_d = rolling_positions(
        fund, factors, sim_mat=sim, min_obs=60, verbose=False
    )
    legacy_w, legacy_d = rolling_positions(
        fund, factors, sim_mat=sim, min_obs=60, equity_cap_mode="legacy", verbose=False
    )
    assert_frame_equal(default_w, legacy_w)
    assert_frame_equal(default_d, legacy_d)


def test_legacy_mode_reproduces_frozen_a21_cap_samples():
    baseline = pd.read_csv("tests/baseline/phaseB2_legacy_equity_cap.csv")
    sample = baseline.drop_duplicates("legacy_cap").tail(18).copy()
    target_dates = pd.to_datetime(sample["date"])
    index_long, stock2sw = load_base()
    nav, holdings, allocation = load_fund("161005")
    sim_mat, _ = SimulatedPortfolio(holdings, allocation, stock2sw, verbose=False).build_all()
    fund_ret, _ = nav_to_returns(nav)
    factor_ret = index_to_returns(index_long)
    _, diagnostics = rolling_positions(
        fund_ret, factor_ret, sim_mat=sim_mat, equity_cap="auto", equity_cap_mode="legacy",
        target_dates=target_dates, verbose=False,
    )
    expected = sample.set_index(pd.to_datetime(sample["date"]))["legacy_cap"].sort_index()
    actual = diagnostics["equity_cap"].reindex(expected.index)
    assert np.allclose(actual.to_numpy(), expected.to_numpy(), atol=1e-12, rtol=0)


def test_disclosure_mode_records_a_complete_cap_source_per_week():
    fund, factors, sim = _synthetic_regression_inputs()
    disclosure = pd.DataFrame([
        alloc_row("2023-12-31", 0.80, "2024-01-30"),
    ])
    _, diagnostics = rolling_positions(
        fund, factors, sim_mat=sim, min_obs=60, equity_cap_mode="disclosure",
        disclosure_index=disclosure, verbose=False,
    )
    assert diagnostics["cap_basis"].eq("INDUSTRY_ALLOC").all()
    assert diagnostics["cap_source_period"].notna().all()
    assert diagnostics["cap_available_date"].notna().all()
    assert np.isfinite(diagnostics["equity_cap"]).all()


def test_equity_cap_audit_has_required_ab_comparison_columns():
    baseline = pd.DataFrame({
        "date": ["2025-04-30"], "legacy_cap": [0.70], "sum_beta": [0.70],
    })
    diagnostics = pd.DataFrame({
        "sum_beta": [0.84], "equity_cap": [0.84], "cap_basis": ["INDUSTRY_ALLOC"],
        "cap_source_period": ["2025-03-31"], "cap_available_date": ["2025-04-30"],
        "cap_reported_equity_ratio": [0.80],
    }, index=pd.DatetimeIndex(["2025-04-30"], name="date"))
    audit = build_equity_cap_audit(baseline, diagnostics)
    assert list(audit.columns) == AUDIT_COLUMNS
    assert audit.loc[0, "cap_binding_legacy"]
    assert audit.loc[0, "cap_binding_new"]
