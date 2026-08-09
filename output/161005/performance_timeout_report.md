# Phase A calibration timeout report

- status: `TIMEOUT_SAFE_STOP`
- completed combos: 118 / 160
- target dates: 49
- total elapsed seconds: 285.765
- average seconds/combo: 2.401
- median seconds/combo: 2.351
- p90 seconds/combo: 2.797
- estimated full seconds: 384.129
- checkpoint saved: True
- watchdog hard kill: False
- residual worker process: False

## Mean duration by dimension

- anchor: nan: 2.589s, 2.5: 2.212s
- window: 60: 2.460s, 90: 2.413s, 120: 2.352s, 180: 2.369s
- half_life: 0: 2.302s, 20: 2.481s, 40: 2.419s, 80: 2.403s
- alpha: 0.0: 2.518s, 1e-07: 2.499s, 1e-06: 2.432s, 1e-05: 2.136s

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

Partial calibration results are diagnostic only and are not production parameters.