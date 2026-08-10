"""Audit helpers for the Phase B2 equity-cap A/B comparison."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


AUDIT_COLUMNS = [
    "date", "legacy_cap", "new_cap", "new_cap_basis", "new_cap_source_period",
    "new_cap_available_date", "reported_equity_ratio", "legacy_sum_beta",
    "new_sum_beta", "cap_binding_legacy", "cap_binding_new",
]


def build_equity_cap_audit(legacy_baseline, diagnostics):
    """Join frozen legacy caps to a disclosure-cap diagnostics frame."""
    legacy = legacy_baseline.copy()
    current = diagnostics.copy()
    if "date" not in legacy.columns:
        legacy = legacy.rename_axis("date").reset_index()
    if "date" not in current.columns:
        current = current.rename_axis("date").reset_index()
    legacy["date"] = pd.to_datetime(legacy["date"]).dt.strftime("%Y-%m-%d")
    current["date"] = pd.to_datetime(current["date"]).dt.strftime("%Y-%m-%d")
    required_legacy = {"date", "legacy_cap", "sum_beta"}
    required_current = {
        "date", "sum_beta", "equity_cap", "cap_basis", "cap_source_period",
        "cap_available_date", "cap_reported_equity_ratio",
    }
    missing = (required_legacy - set(legacy.columns)) | (required_current - set(current.columns))
    if missing:
        raise ValueError(f"Equity cap audit missing columns: {sorted(missing)}")

    joined = legacy.merge(
        current[[
            "date", "sum_beta", "equity_cap", "cap_basis", "cap_source_period",
            "cap_available_date", "cap_reported_equity_ratio",
        ]],
        on="date", how="outer", validate="one_to_one", indicator=True,
    )
    if not joined["_merge"].eq("both").all():
        raise ValueError("Legacy baseline and new diagnostics dates do not match")
    audit = pd.DataFrame({
        "date": joined["date"],
        "legacy_cap": pd.to_numeric(joined["legacy_cap"], errors="coerce"),
        "new_cap": pd.to_numeric(joined["equity_cap"], errors="coerce"),
        "new_cap_basis": joined["cap_basis"].fillna(""),
        "new_cap_source_period": joined["cap_source_period"].fillna(""),
        "new_cap_available_date": joined["cap_available_date"].fillna(""),
        "reported_equity_ratio": pd.to_numeric(
            joined["cap_reported_equity_ratio"], errors="coerce"
        ),
        "legacy_sum_beta": pd.to_numeric(joined["sum_beta_x"], errors="coerce"),
        "new_sum_beta": pd.to_numeric(joined["sum_beta_y"], errors="coerce"),
    })
    required_numeric = ("legacy_cap", "new_cap", "legacy_sum_beta", "new_sum_beta")
    if audit[list(required_numeric)].isna().any().any():
        raise ValueError("Equity cap audit contains missing numeric values")
    audit["cap_binding_legacy"] = np.isclose(
        audit["legacy_sum_beta"], audit["legacy_cap"], atol=1e-6, rtol=0
    )
    audit["cap_binding_new"] = np.isclose(
        audit["new_sum_beta"], audit["new_cap"], atol=1e-6, rtol=0
    )
    return audit[AUDIT_COLUMNS]


def write_equity_cap_audit(legacy_path, diagnostics, output_path):
    legacy_path = Path(legacy_path)
    output_path = Path(output_path)
    audit = build_equity_cap_audit(pd.read_csv(legacy_path), diagnostics)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output_path, index=False, encoding="utf-8-sig")
    return audit
