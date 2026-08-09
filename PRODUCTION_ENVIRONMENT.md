# FundTrace Production Environment

- Model: `v4-a2.1-stable`
- Production reference commit: `ca4d14aa4362130d0708a2cda948f21f9d27b87b`
- Python: `3.12.13`
- Baseline: `tests/baseline/v4_a2_1_production/`
- Weekly baseline SHA256: `ecc1a1cfa1d851347d27fb63560cdfbd625001cdb23c646af4e572229584169f`

## Locked production packages

- akshare `1.18.83`
- fastapi `0.141.1`
- matplotlib `3.11.1`
- numpy `2.5.1`
- pandas `3.0.5`
- pydantic `2.13.4`
- requests `2.34.2`
- streamlit `1.61.1`
- uvicorn `0.52.1`

The lock was verified in a clean Windows venv. The 161005 quick analysis completed in `14.985` seconds with `max_abs_diff=0.0`, identical industry columns, diagnostics Σβ difference `0.0`, and Top5 consistency `1044/1044`.

Regression command:

```bash
python tools/check_production_regression.py 161005
```

Run this regression again before accepting any dependency update. The Windows launcher checks `requirements-lock.txt` and installs only when the active environment is missing or does not match the verified pins.
