# Windows portable distribution

FundTrace V1.2 is distributed to non-technical Windows users as a self-contained ZIP. The GitHub repository remains the source distribution; the portable ZIP is a Release asset and is not committed to Git.

## Runtime layout

```text
FundTrace_Windows_Portable/
├─ 启动FundTrace.bat
├─ README_使用说明.txt
├─ THIRD_PARTY_NOTICES.txt
├─ runtime/python.exe
├─ app/
└─ logs/
```

The runtime is the official CPython 3.12.7 Windows embeddable package from python.org with the exact packages from `requirements-lock.txt` preinstalled. The launcher only invokes `runtime\python.exe`; it never probes `py`, `python`, `python3`, PATH, Conda, or a local virtual environment, and it never runs pip.

## Release contents

Include the production API, model library, base data, built React assets, required fund/output data, runtime configuration, lock file, notices, and user instructions. Exclude `.git`, `.venv`, `node_modules`, caches, tests, research material, calibration artifacts, benchmarks, and development logs.

## Release verification

Before publishing, verify imports and locked versions with the bundled Python, run `tools/check_production_regression.py 161005` while the temporary baseline is present, confirm `max_abs_diff == 0`, Top5 matches all 1044 rows, and 27/27 industry columns match. Then test health and homepage HTTP 200 from a Chinese extraction path. Never run `--calibrate` as part of packaging.

