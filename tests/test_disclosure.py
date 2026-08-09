import numpy as np
import pandas as pd

from lib.disclosure import build_disclosure_index, report_type_for_period


def holdings(period, count, total_pct, codes=None):
    codes = codes or [f"{index:06d}" for index in range(count)]
    return pd.DataFrame({
        "period_end": [period] * count,
        "stock_code": codes,
        "holding_pct": [total_pct / count] * count,
    })


def alloc(period, total_pct):
    return pd.DataFrame({"period_end": [period], "allocation_pct": [total_pct]})


def one_row(index):
    assert len(index) == 1
    return index.iloc[0]


def test_ratio_gap_and_percent_unit_conversion():
    index = build_disclosure_index(
        holdings("2024-06-30", 20, 90), alloc("2024-06-30", 95), fund_code="161005"
    )
    row = one_row(index)
    assert np.isclose(row.holdings_sum, 0.90)
    assert np.isclose(row.reported_equity_ratio, 0.95)
    assert np.isclose(row.coverage_ratio, 0.90 / 0.95)
    assert np.isclose(row.coverage_gap, 0.05)


def test_many_rows_with_low_coverage_is_partial_not_full():
    row = one_row(build_disclosure_index(
        holdings("2024-06-30", 16, 80), alloc("2024-06-30", 100)
    ))
    assert row.coverage_type == "PARTIAL"


def test_rows_at_topline_are_truncated_even_with_high_coverage():
    row = one_row(build_disclosure_index(
        holdings("2024-12-31", 100, 98), alloc("2024-12-31", 100), topline_used=100
    ))
    assert row.coverage_type == "TOP_N_TRUNCATED"
    assert "TOPLINE_LIMIT" in row["flags"]


def test_high_coverage_below_topline_can_be_full_confirmed():
    row = one_row(build_disclosure_index(
        holdings("2024-12-31", 99, 98), alloc("2024-12-31", 100), topline_used=100
    ))
    assert row.coverage_type == "FULL_CONFIRMED"


def test_missing_allocation_never_becomes_full():
    row = one_row(build_disclosure_index(holdings("2024-12-31", 20, 98), pd.DataFrame()))
    assert row.coverage_type == "UNKNOWN"
    assert np.isnan(row.coverage_ratio)


def test_top10_and_report_type_are_recognised():
    row = one_row(build_disclosure_index(
        holdings("2024-06-30", 10, 40), alloc("2024-06-30", 95)
    ))
    assert row.coverage_type == "TOP10"
    assert report_type_for_period("2024-06-30") == "INTERIM"
    assert report_type_for_period("2024-02-29") == "UNKNOWN"


def test_duplicate_and_malformed_rows_are_flagged():
    frame = holdings("2024-12-31", 2, 98, codes=["000001", "000001"])
    frame["holding_pct"] = frame["holding_pct"].astype(object)
    frame.loc[1, "holding_pct"] = "not-a-number"
    row = one_row(build_disclosure_index(frame, alloc("2024-12-31", 100)))
    assert "DUPLICATE" in row["flags"]
    assert "MALFORMED" in row["flags"]
    assert row.coverage_type != "FULL_CONFIRMED"


def test_quarterly_rows_are_conservatively_partial_and_unverified():
    row = one_row(build_disclosure_index(
        holdings("2024-03-31", 26, 98), alloc("2024-03-31", 100)
    ))
    assert row.coverage_type == "PARTIAL"
    assert "QUARTERLY_PARTIAL" in row["flags"]
    assert "SOURCE_UNVERIFIED" in row["flags"]


def test_index_has_one_row_per_union_of_report_periods():
    index = build_disclosure_index(
        pd.concat([holdings("2024-03-31", 10, 30), holdings("2024-06-30", 20, 90)]),
        pd.concat([alloc("2024-06-30", 95), alloc("2024-09-30", 90)]),
    )
    assert len(index) == 3
    assert set(index.period_end) == {"2024-03-31", "2024-06-30", "2024-09-30"}
