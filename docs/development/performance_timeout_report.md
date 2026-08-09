# Phase A calibration timeout report

- status: `TIMEOUT_SAFE_STOP`
- completed combos: 84 / 160
- target dates: 49
- total elapsed seconds: 288.938
- parent-observed calibration seconds: 290.120
- average seconds/combo: 3.419
- median seconds/combo: 3.141
- p90 seconds/combo: 5.647
- estimated full seconds: 546.981
- checkpoint saved: True
- watchdog hard kill: False
- residual worker process: False

## Mean duration by dimension

- anchor: nan: 1.692s, 2.5: 5.146s
- window: 60: 3.425s, 90: 3.463s, 120: 3.336s
- half_life: 0: 3.350s, 20: 3.769s, 40: 3.305s, 80: 3.139s
- alpha: 0.0: 3.480s, 1e-07: 3.489s, 1e-06: 3.559s, 1e-05: 3.132s

## Slowest 10 combinations

- `w90_h20_a1e-06_anchor2.5`: 7.032s
- `w60_h20_a1e-07_anchor2.5`: 6.281s
- `w60_h20_a0_anchor2.5`: 6.219s
- `w90_h20_a0_anchor2.5`: 6.156s
- `w60_h20_a1e-06_anchor2.5`: 6.063s
- `w90_h20_a1e-05_anchor2.5`: 5.782s
- `w90_h20_a1e-07_anchor2.5`: 5.781s
- `w90_h0_a1e-07_anchor2.5`: 5.766s
- `w120_h20_a1e-06_anchor2.5`: 5.703s
- `w90_h0_a1e-06_anchor2.5`: 5.516s

Partial calibration results are diagnostic only and are not production parameters.

The worker exited normally at the 285-second safe-stop boundary. No hard kill or
solver modification occurred during this A1 run. The later console encoding error
happened after calibration, while the default report path was printing `R²`, and
does not affect these calibration artifacts.
