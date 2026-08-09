# UI V1.1 Reproducibility Audit

## Conclusion

`ROOT_CAUSE_NUMERICAL_ENVIRONMENT`

Model source, default parameters, and all five default-analysis input files are identical between the UI V1 ZIP and this audit workspace. The result drift is caused by a Pandas behavioral change in `DataFrame.pct_change()`:

- Pandas 2.3.3 implicitly forward-fills missing factor observations. Coal therefore has 3,012 non-null observations and passes the `> 2,507.5` validity threshold.
- Pandas 3.0.1 and 3.0.5 do not perform that implicit fill. Coal has 1,826 non-null observations and is excluded; both environments reproduce the packaged weekly CSV byte-for-byte.
- The writer does not remove zero-only columns. `rolling_positions()` writes exactly the factor columns that pass `valid_cols`, so this is not output-only schema drift.

No solver, model parameter, or input was changed to obtain these results.

## Packaged vs Pandas 2.3.3 fresh

- Dates: identical, 1,044 rows.
- Industry columns: 27 vs 28; fresh-only column is `煤炭`.
- Maximum absolute difference: `0.0736828142163404`.
- Mean / p95 / p99 absolute difference: `0.00026340792573442483` / `3.748710884349235e-08` / `0.008240142835957665`.
- Top1 / Top5 consistency: `1041/1044` / `1021/1044`.
- Maximum weekly Σβ difference: `0.02640236656293027`.
- Maximum diagnostics Σβ / R² difference: `0.02640236656293049` / `0.004707979761103487`.
- Convergence flag mismatches: `0`.
- Parameters: identical (`window=120`, `half_life=40`, `alpha=1e-6`, `anchor=None`, `equity_cap=auto`, `index_proxy`).

Coal is absent from the packaged weekly schema. In the Pandas 2.3.3 fresh result its first positive date is `2015-06-26`; maximum exposure is `6.62636142807664%` on `2015-07-17`, with 101 positive rows.

## Production reference

The production reference is the formally accepted `v4-a2.1-stable` asset:

- Commit: `ca4d14aa4362130d0708a2cda948f21f9d27b87b`
- Archive: `FundTrace_V4_A2.1_验收包.zip::Fundtrace/output/161005/weekly_positions.csv`
- SHA256: `ecc1a1cfa1d851347d27fb63560cdfbd625001cdb23c646af4e572229584169f`
- Repository fixture: `tests/baseline/v4_a2_1_production/`
