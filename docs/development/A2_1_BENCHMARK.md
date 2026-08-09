# V4 A2.1 projection hot-path validation

- Change: `cap=None` now uses the existing exact `project_capped_simplex` path.
- KKT check frequency change: not needed; the 18-combo estimate was already below 250 seconds.
- Projection equivalence: 500 random vectors across K=5/27/31 and B=0.5/0.8/0.95/1.0; maximum absolute difference `4.991562718714704e-13`.
- A2 generic-path numerical comparison (anchor=None): maximum absolute difference `3.7842992628434047e-13`; Top5 unchanged.
- SciPy reference on 100 real solver samples: maximum beta difference `4.6565336506154686e-7`; constraints and objective checks passed.

## Short benchmark (49 target dates, 18 representative combinations)

- anchor=None mean: 0.529948 seconds/combo
- anchor=2.5 mean: 2.049189 seconds/combo
- overall mean / median / p90: 1.289568 / 1.188775 / 2.158687 seconds
- estimated 160 combinations: 206.331 seconds

## Formal calibration

- New solver code hash invalidated the A2 checkpoint; the run started at 0/160.
- Completed: 160/160
- worker elapsed: 227.187 seconds
- parent-observed calibration elapsed: 228.330 seconds
- safe stop / hard watchdog: not triggered / not triggered
- target dates / solver calls / error matrix: 49 / 7,840 / 160 x 17
- candidate: `best_params_phaseA_candidate.json`, explicitly `production_eligible: false`
- production `best_params.json`: not generated

## Fast analysis and result stability

- A2.1 fast analysis: 13.791 seconds
- V3 baseline: 38.987 seconds; A2: 46.469 seconds
- V3 weekly-position maximum absolute difference: `4.825139105595899e-4`
- A2 to A2.1 weekly-position maximum absolute difference: `1.0967271993345129e-8`
- Top5 consistency with V3 baseline: 1044/1044
