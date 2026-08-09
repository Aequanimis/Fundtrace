@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo [FundTrace] 首次启动，正在创建本地 Python 环境...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv ".venv"
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo [FundTrace] 未找到 Python 3，请先安装后重试。
      pause
      exit /b 1
    )
    python -m venv ".venv"
  )
  if errorlevel 1 goto :failed
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn, pandas, numpy" >nul 2>nul
if errorlevel 1 (
  echo [FundTrace] 正在安装首次运行所需组件...
  "%PYTHON_EXE%" -m pip install -r "requirements.txt"
  if errorlevel 1 goto :failed
)

if not exist "frontend\dist\index.html" (
  echo [FundTrace] 缺少已构建的前端文件 frontend\dist\index.html。
  pause
  exit /b 1
)

echo [FundTrace] 正在启动：http://127.0.0.1:8765/
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765/'"
"%PYTHON_EXE%" -m api.server
exit /b %errorlevel%

:failed
echo [FundTrace] 启动失败，请检查上方错误信息。
pause
exit /b 1
