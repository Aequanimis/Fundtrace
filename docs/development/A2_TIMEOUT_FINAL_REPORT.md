# A2 timeout final report

- status: `TIMEOUT_SAFE_STOP`
- completed combos: 118 / 160
- target dates: 49
- worker elapsed seconds: 285.765
- parent-observed calibration seconds: 286.980
- average seconds/combo: 2.401
- median seconds/combo: 2.351
- p90 seconds/combo: 2.797
- estimated full seconds: 384.129
- actual solver calls: 5,782
- error matrix shape: 118 x 17
- checkpoint saved: yes
- hard watchdog triggered: no
- residual calibration worker/child process: no
- production `best_params.json` generated: no
- Phase A candidate generated: no

## Mean duration by dimension

- anchor: None 2.589s; 2.5 2.212s
- window: 60 2.460s; 90 2.413s; 120 2.352s; 180 2.369s
- half_life: 0 2.302s; 20 2.481s; 40 2.419s; 80 2.403s
- alpha: 0 2.518s; 1e-7 2.499s; 1e-6 2.432s; 1e-5 2.136s

## Slowest 10 combinations

- `w180_h0_a0_anchornone`: 2.969s
- `w60_h20_a0_anchornone`: 2.937s
- `w60_h20_a1e-07_anchornone`: 2.922s
- `w90_h40_a1e-07_anchornone`: 2.828s
- `w90_h20_a0_anchornone`: 2.828s
- `w60_h20_a1e-06_anchornone`: 2.828s
- `w60_h0_a1e-07_anchornone`: 2.828s
- `w90_h40_a0_anchornone`: 2.828s
- `w90_h20_a1e-06_anchornone`: 2.812s
- `w60_h40_a0_anchornone`: 2.797s

The complete 160-combination A2 calibration did not finish inside the five-minute
rule. It stopped normally after the last complete combination beyond the
285-second safe boundary. No grid reduction, parallelism, or further automatic
solver optimization was performed.

Detailed per-dimension timings and the ten slowest combinations remain in
`performance_timeout_report.md`.
