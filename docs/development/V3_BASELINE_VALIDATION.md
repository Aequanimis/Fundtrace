# V3 baseline validation

- Validation date: 2026-08-09
- Fund: `161005`
- Network fetch: not used
- Calibration: not used
- Command: `python run_analysis.py 161005`
- Fast-analysis elapsed time: `38.987` seconds
- Mode: `FULL`
- NAV column: `nav_adj`
- Weekly points: `1044`
- Median R²: `0.919`
- Median Σβ: `0.884`
- Non-converged points reported by V3: `528`

## Numeric comparison against `tests/baseline/161005`

| File | Shape | `np.array_equal` | `max_abs_diff` |
|---|---:|---:|---:|
| `weekly_positions.csv` | 1044 × 27 | true | 0.0 |
| `diagnostics.csv` | 1044 × 5 | true | 0.0 |
| `sim_portfolio.csv` | 18 × 31 | true | 0.0 |

Index, columns and numeric dtypes were normalized before comparison. Non-numeric diagnostic columns were also equal.

Static compilation succeeded and the migrated V3 test suite completed with `10 passed`.
