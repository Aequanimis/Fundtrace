@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto check_dependencies

set "BOOTSTRAP_PY="
set "USE_PY_LAUNCHER="

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "USE_PY_LAUNCHER=1"
        goto create_venv
    )
)

for /f "delims=" %%P in ('where python 2^>nul') do call :try_python "%%P"
if defined BOOTSTRAP_PY goto create_venv

for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do call :try_python "%%~fD\python.exe"
if defined BOOTSTRAP_PY goto create_venv

call :try_python "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if defined BOOTSTRAP_PY goto create_venv

echo.
echo [无法启动] 未找到可用的 Python 3。
echo 请先安装 Python 3，安装时勾选“Add Python to PATH”，然后再次双击本文件。
echo.
pause
exit /b 1

:try_python
if defined BOOTSTRAP_PY exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; assert sys.version_info.major == 3" >nul 2>nul
if not errorlevel 1 set "BOOTSTRAP_PY=%~1"
exit /b 0

:create_venv
echo 正在创建本地运行环境，首次启动需要几分钟……
if defined USE_PY_LAUNCHER (
    py -3 -m venv "%~dp0.venv"
) else (
    "%BOOTSTRAP_PY%" -m venv "%~dp0.venv"
)
if errorlevel 1 goto venv_failed
if not exist "%VENV_PY%" goto venv_failed

:check_dependencies
"%VENV_PY%" -c "import akshare, matplotlib, numpy, pandas, requests, streamlit" >nul 2>nul
if not errorlevel 1 goto start_app

echo 正在安装运行所需组件，首次启动需要几分钟……
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto install_failed

:start_app
echo 正在启动基金高频持仓分析，请稍候……
"%VENV_PY%" -m streamlit run "%~dp0app.py" --server.headless false --browser.gatherUsageStats false
if errorlevel 1 goto app_failed
exit /b 0

:venv_failed
echo.
echo [启动失败] 无法创建本地运行环境，请检查 Python 安装是否完整。
echo.
pause
exit /b 1

:install_failed
echo.
echo [启动失败] 运行组件安装失败，请检查网络连接后重试。
echo.
pause
exit /b 1

:app_failed
echo.
echo [程序已停止] 如页面未打开，请查看上方错误信息。
echo.
pause
exit /b 1
