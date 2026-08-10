# Phase B2 Equity Cap Comparison

- Scope: only the equity-cap source/timing changed; no calibration was run.
- Allocation availability: local files have no actual announcement-date field, so `period_end + 30 calendar days` is used conservatively.
- Holdings availability remains `UNVERIFIED_PHASE_B3`; partial/TOP-N holdings never set a cap.

## Aggregate comparison

| Metric | Legacy | Disclosure |
|---|---:|---:|
| Cap (min / median / max) | 53.72%/95.00%/97.32% | 95.00%/95.00%/98.00% |
| Σβ (min / median / max) | 48.05%/88.43%/97.32% | 48.05%/90.23%/98.00% |
| Cap binding ratio | 36.40% | 25.86% |
| Reported equity ratio (min / median / max) | — | 93.65%/94.40%/94.53% |

## Quarterly timing check

| Q1/Q3 period | Alloc available | Legacy cap median | New cap median | Legacy Σβ median | New Σβ median |
|---|---|---:|---:|---:|---:|
| 2022-03-31 | 2022-04-30 | 95.00% | 98.00% | 92.42% | 92.42% |
| 2022-09-30 | 2022-10-30 | 97.08% | 98.00% | 90.50% | 90.50% |
| 2023-03-31 | 2023-04-30 | 96.63% | 98.00% | 90.65% | 90.65% |
| 2023-09-30 | 2023-10-30 | 96.44% | 98.00% | 89.28% | 89.28% |
| 2024-03-31 | 2024-04-30 | 97.32% | 98.00% | 94.84% | 94.84% |
| 2024-09-30 | 2024-10-30 | 96.22% | 98.00% | 92.90% | 92.90% |
| 2025-03-31 | 2025-04-30 | 94.76% | 98.00% | 90.79% | 90.79% |
| 2025-09-30 | 2025-10-30 | 92.21% | 98.00% | 92.21% | 93.68% |
| 2026-03-31 | 2026-04-30 | 92.03% | 98.00% | 92.03% | 96.44% |

- Q1/Q3 low-cap anomaly materially reduced: **NO**.
- Top-5 industry set consistency: **91.28%**; weekly position max absolute difference: **0.214713**.
- Model-change gate: **MATERIAL_MODEL_CHANGE**.
- Disclosure cap sources: `{"CONSTANT_FALLBACK": 826, "INDUSTRY_ALLOC": 218}`.

The disclosure cap is an upper bound, not a forced equality to the reported equity ratio.
