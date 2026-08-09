@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo [FundTrace] First launch: creating the local Python environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo [FundTrace] Python 3 was not found. Install Python and try again.
      pause
      exit /b 1
    )
    python -m venv ".venv"
  )
  if errorlevel 1 goto :failed
)

"%PYTHON_EXE%" "tools\check_locked_environment.py" >nul 2>nul
if errorlevel 1 (
  echo [FundTrace] Installing or repairing locked production dependencies...
  "%PYTHON_EXE%" -m pip install -r "requirements-lock.txt"
  if errorlevel 1 goto :failed
)

if not exist "frontend\dist\index.html" (
  echo [FundTrace] Missing frontend\dist\index.html.
  pause
  exit /b 1
)

echo [FundTrace] Starting http://127.0.0.1:8765/
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765/'"
"%PYTHON_EXE%" -m api.server
exit /b %errorlevel%

:failed
echo [FundTrace] Startup failed. Review the error above.
pause
exit /b 1
