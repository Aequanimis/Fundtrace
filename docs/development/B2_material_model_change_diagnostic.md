# B2 Material Model Change Diagnostic

Scope: static comparison of frozen B1 legacy artifacts and the existing B2 disclosure-cap output. No model or calibration rerun was performed.

## Result

- Top-5 consistency is **91.28%** (91/1044 changed).
- Classification: A 120 (11.49%), B 6 (0.57%), C 0 (0.00%), D 918 (87.93%).
- The largest industry change is **+21.47%** on 2026-03-13: 交通运输 (0.25% → 21.72%); legacy cap binding=True; TYPE_A_CAP_RELEASED.
- Legacy cap actually released the fitted exposure in A/B for 126/1044 weeks (12.07%).
- Legacy minimum Σβ is 48.05% on 2006-02-24; cap binding=False. New minimum is 48.05% on 2006-02-24; cap binding=False.
- 590/1044 legacy weeks have Σβ < cap − 2pp: these low implied exposures are not directly caused by the legacy equity cap.
- Input audit: **INPUTS_CONFIRMED_IDENTICAL** (X/y/prior precede the cap branch, run parameters and simulated portfolio match; disclosure row selection is the intended cap-source change).
- R² relation: changed weeks legacy/new median R² = 0.882/0.912; unchanged = 0.924/0.926.
- Conclusion: **B2_CHANGE_MOSTLY_EXPLAINED_BY_CAP_RELEASE**.

## Top-5 changes

- Range: 2022-07-22 to 2026-08-07; Q1/Q3-source weeks 33/91; legacy cap <80% weeks 87/91.
- Types among changed weeks: `{"TYPE_A_CAP_RELEASED": 91}`.
- By year: `{"2014": 0, "2015": 0, "2016": 0, "2017": 0, "2018": 0, "2019": 0, "2020": 0, "2021": 0, "2022": 4, "2023": 18, "2024": 23, "2025": 25, "2026": 21}`.

## R² bands

| Legacy R² band | Weeks | Top-5 change rate |
|---|---:|---:|
| <0.3 | 0 | nan% |
| 0.3-0.6 | 6 | 0.00% |
| >0.6 | 1038 | 8.77% |

## Top 20 one-industry differences

| date | industry | legacy_weight | new_weight | difference | legacy_cap | new_cap | type |
|---|---|---|---|---|---|---|---|
| 2026-03-13 | 交通运输 | 0.25% | 21.72% | +21.47% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-03-27 | 汽车 | 0.00% | 20.46% | +20.46% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-01-16 | 家用电器 | 0.00% | 19.93% | +19.93% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-01-23 | 家用电器 | 2.06% | 21.68% | +19.62% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-07-24 | 银行 | 0.00% | 18.18% | +18.18% | 59.46% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-03-06 | 交通运输 | 0.00% | 17.64% | +17.64% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-01-09 | 家用电器 | 0.00% | 17.60% | +17.60% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-07-31 | 银行 | 0.00% | 17.48% | +17.48% | 59.46% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-03-20 | 汽车 | 1.15% | 18.31% | +17.16% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2025-03-28 | 银行 | 0.00% | 16.79% | +16.79% | 65.90% | 98.00% | TYPE_A_CAP_RELEASED |
| 2024-03-22 | 家用电器 | 0.96% | 17.58% | +16.62% | 67.12% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-01-30 | 家用电器 | 2.21% | 18.31% | +16.10% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2024-03-29 | 家用电器 | 1.06% | 16.91% | +15.85% | 67.12% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-07-17 | 家用电器 | 0.00% | 15.71% | +15.71% | 59.46% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-08-07 | 银行 | 0.00% | 15.40% | +15.40% | 59.46% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-01-02 | 家用电器 | 0.00% | 15.18% | +15.18% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-07-03 | 家用电器 | 0.00% | 15.07% | +15.07% | 59.46% | 98.00% | TYPE_A_CAP_RELEASED |
| 2024-03-15 | 家用电器 | 0.00% | 14.84% | +14.84% | 67.12% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-02-13 | 家用电器 | 0.00% | 14.43% | +14.43% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |
| 2026-02-06 | 家用电器 | 0.00% | 14.27% | +14.27% | 53.72% | 98.00% | TYPE_A_CAP_RELEASED |

## Decision

Do not continue B2 automatically while Top-5 consistency remains below 95%. Keep A2.1 legacy as the current MVP until the sensitivity is independently accepted or a later design narrows the change scope.
