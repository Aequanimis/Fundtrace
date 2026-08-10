@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "LOG_DIR=%CD%\logs"
set "STARTUP_LOG=%LOG_DIR%\startup.log"
set "STAGE_LOG=%LOG_DIR%\startup-stage-%RANDOM%-%RANDOM%.tmp"
set "PYTHON_BOOTSTRAP="
set "PYTHON_DISPLAY="
set "PYTHON_VERSION="

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
call :log startup "FundTrace launcher started"

echo [FundTrace] Checking Python 3.12...
call :log python_detection "Checking existing local environment"

if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" --version >"%STAGE_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :record_stage venv_validation "%PYTHON_EXE% --version" "!RC!"
  if "!RC!"=="0" (
    set /p "VENV_VERSION="<"%STAGE_LOG%"
    echo !VENV_VERSION! | findstr /b /c:"Python 3.12." >nul
    if not errorlevel 1 goto :venv_ready
  )
  echo [FundTrace] Existing .venv is incomplete, broken, or not Python 3.12.
  call :log venv_validation "BROKEN_VENV_REMOVED"
  rmdir /s /q "%CD%\.venv"
) else if exist "%CD%\.venv" (
  echo [FundTrace] Existing .venv is incomplete or broken.
  call :log venv_validation "BROKEN_VENV_REMOVED"
  rmdir /s /q "%CD%\.venv"
)

call :find_python312
if errorlevel 1 goto :python_missing

echo [FundTrace] Python 3.12 detected: !PYTHON_VERSION!
echo [FundTrace] Creating local environment...
call :log venv_creation "command=!PYTHON_DISPLAY! -m venv .venv"
!PYTHON_BOOTSTRAP! -m venv ".venv" >"%STAGE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :record_stage venv_creation "!PYTHON_DISPLAY! -m venv .venv" "!RC!"
if not "!RC!"=="0" goto :venv_failed

if not exist "%PYTHON_EXE%" (
  set "RC=1"
  >"%STAGE_LOG%" echo .venv\Scripts\python.exe was not created.
  call :record_stage venv_validation "%PYTHON_EXE% --version" "!RC!"
  goto :venv_failed
)

"%PYTHON_EXE%" --version >"%STAGE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :record_stage venv_validation "%PYTHON_EXE% --version" "!RC!"
if not "!RC!"=="0" goto :venv_failed
set /p "VENV_VERSION="<"%STAGE_LOG%"
echo !VENV_VERSION! | findstr /b /c:"Python 3.12." >nul
if errorlevel 1 goto :venv_wrong_version
echo [FundTrace] Local environment created.

:venv_ready
if not defined VENV_VERSION (
  "%PYTHON_EXE%" --version >"%STAGE_LOG%" 2>&1
  set /p "VENV_VERSION="<"%STAGE_LOG%"
)
echo [FundTrace] Local environment: !VENV_VERSION!
echo [FundTrace] Checking verified dependencies...
call :log dependency_check "command=%PYTHON_EXE% tools\check_locked_environment.py"
"%PYTHON_EXE%" "tools\check_locked_environment.py" >"%STAGE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :record_stage dependency_check "%PYTHON_EXE% tools\check_locked_environment.py" "!RC!"
if "!RC!"=="0" goto :dependencies_ready

echo [FundTrace] Installing missing dependencies...
call :log dependency_install "command=%PYTHON_EXE% -m pip install -r requirements-lock.txt"
"%PYTHON_EXE%" -m pip install -r "requirements-lock.txt" >"%STAGE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :record_stage dependency_install "%PYTHON_EXE% -m pip install -r requirements-lock.txt" "!RC!"
if not "!RC!"=="0" goto :dependency_failed

"%PYTHON_EXE%" "tools\check_locked_environment.py" >"%STAGE_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :record_stage dependency_verification "%PYTHON_EXE% tools\check_locked_environment.py" "!RC!"
if not "!RC!"=="0" goto :dependency_failed

:dependencies_ready
call :current_runtime_identity
call :log runtime_identity "expected_commit=!CURRENT_GIT_COMMIT! branch=!CURRENT_GIT_BRANCH!"
call :log runtime_port_guard "Checking port 8765 before starting FundTrace"
"%PYTHON_EXE%" "tools\runtime_port_guard.py" --expected-commit "!CURRENT_GIT_COMMIT!" >"%STAGE_LOG%" 2>&1
set "PORT_GUARD_RC=!ERRORLEVEL!"
call :record_stage runtime_port_guard "%PYTHON_EXE% tools\runtime_port_guard.py --expected-commit !CURRENT_GIT_COMMIT!" "!PORT_GUARD_RC!"
if "!PORT_GUARD_RC!"=="10" (
  echo [FundTrace] Current FundTrace is already running on port 8765.
  echo [FundTrace] Opening the matching local version...
  call :log runtime_port_guard "classification=CURRENT_RUNTIME_REUSED commit=!CURRENT_GIT_COMMIT!"
  start "" "http://127.0.0.1:8765/"
  exit /b 0
)
if "!PORT_GUARD_RC!"=="20" (
  echo [FundTrace] ERROR: Port 8765 is occupied by another application.
  echo [FundTrace] FundTrace was not started and the other application was not stopped.
  echo [FundTrace] Log: %STARTUP_LOG%
  call :log failure "classification=PORT_8765_OCCUPIED_BY_OTHER_APP"
  pause
  exit /b 1
)
if not "!PORT_GUARD_RC!"=="0" (
  echo [FundTrace] ERROR: Could not safely resolve the existing service on port 8765.
  echo [FundTrace] Log: %STARTUP_LOG%
  call :log failure "classification=RUNTIME_PORT_GUARD_FAILED exit_code=!PORT_GUARD_RC!"
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  set "RC=1"
  >"%STAGE_LOG%" echo Missing frontend\dist\index.html.
  call :record_stage frontend_check "frontend\dist\index.html" "!RC!"
  goto :fastapi_failed
)

echo [FundTrace] Starting FundTrace...
echo [FundTrace] URL: http://127.0.0.1:8765/
call :log fastapi_start "command=%PYTHON_EXE% tools\run_server_logged.py; host=127.0.0.1; port=8765"
set "FUNDTRACE_GIT_COMMIT=!CURRENT_GIT_COMMIT!"
set "FUNDTRACE_GIT_BRANCH=!CURRENT_GIT_BRANCH!"
set "FUNDTRACE_OPEN_BROWSER=1"
"%PYTHON_EXE%" "tools\run_server_logged.py"
set "RC=!ERRORLEVEL!"
call :log fastapi_exit "exit_code=!RC!"
if not "!RC!"=="0" goto :fastapi_failed
exit /b 0

:find_python312
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 --version >"%STAGE_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :record_stage python_detection "py -3.12 --version" "!RC!"
  if "!RC!"=="0" (
    set /p "PYTHON_VERSION="<"%STAGE_LOG%"
    echo !PYTHON_VERSION! | findstr /b /c:"Python 3.12." >nul
    if not errorlevel 1 (
      set "PYTHON_BOOTSTRAP=py -3.12"
      set "PYTHON_DISPLAY=py -3.12"
      exit /b 0
    )
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  python --version >"%STAGE_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :record_stage python_detection "python --version" "!RC!"
  if "!RC!"=="0" (
    set /p "PYTHON_VERSION="<"%STAGE_LOG%"
    echo !PYTHON_VERSION! | findstr /b /c:"Python 3.12." >nul
    if not errorlevel 1 (
      set "PYTHON_BOOTSTRAP=python"
      set "PYTHON_DISPLAY=python"
      exit /b 0
    )
  )
)

set "REGISTERED_PYTHON_DIR="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Python\PythonCore\3.12\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do set "REGISTERED_PYTHON_DIR=%%B"
if defined REGISTERED_PYTHON_DIR (
  set "REGISTERED_PYTHON=!REGISTERED_PYTHON_DIR!\python.exe"
  if exist "!REGISTERED_PYTHON!" (
    "!REGISTERED_PYTHON!" --version >"%STAGE_LOG%" 2>&1
    set "RC=!ERRORLEVEL!"
    call :record_stage python_detection "registered Python 3.12 --version" "!RC!"
    if "!RC!"=="0" (
      set /p "PYTHON_VERSION="<"%STAGE_LOG%"
      echo !PYTHON_VERSION! | findstr /b /c:"Python 3.12." >nul
      if not errorlevel 1 (
        set PYTHON_BOOTSTRAP="!REGISTERED_PYTHON!"
        set "PYTHON_DISPLAY=!REGISTERED_PYTHON!"
        exit /b 0
      )
    )
  )
)
exit /b 1

:current_runtime_identity
set "CURRENT_GIT_COMMIT=unknown"
set "CURRENT_GIT_BRANCH=unknown"
for /f "delims=" %%G in ('git rev-parse HEAD 2^>nul') do set "CURRENT_GIT_COMMIT=%%G"
for /f "delims=" %%G in ('git branch --show-current 2^>nul') do set "CURRENT_GIT_BRANCH=%%G"
exit /b 0

:record_stage
if exist "%STAGE_LOG%" type "%STAGE_LOG%"
>>"%STARTUP_LOG%" echo [%date% %time%] stage=%~1
>>"%STARTUP_LOG%" echo command=%~2
>>"%STARTUP_LOG%" echo exit_code=%~3
if exist "%STAGE_LOG%" type "%STAGE_LOG%" >>"%STARTUP_LOG%"
>>"%STARTUP_LOG%" echo.
exit /b 0

:log
>>"%STARTUP_LOG%" echo [%date% %time%] stage=%~1 %~2
exit /b 0

:python_missing
echo [FundTrace] ERROR: Python 3.12.x was not found.
echo [FundTrace] Install official Python 3.12, then run this launcher again.
echo [FundTrace] Log: %STARTUP_LOG%
call :log failure "classification=PYTHON_312_INSTALLATION_REQUIRED"
pause
exit /b 1

:venv_failed
echo [FundTrace] ERROR: Failed to create local environment.
echo Python command: !PYTHON_DISPLAY!
echo Exit code: !RC!
echo Log: %STARTUP_LOG%
call :log failure "classification=VENV_CREATION_FAILED exit_code=!RC!"
pause
exit /b 1

:venv_wrong_version
echo [FundTrace] ERROR: Local environment is not Python 3.12.x.
echo Exit code: !RC!
echo Log: %STARTUP_LOG%
call :log failure "classification=VENV_CREATION_FAILED wrong_python_version=!VENV_VERSION!"
pause
exit /b 1

:dependency_failed
echo [FundTrace] ERROR: Failed to install or verify locked dependencies.
echo Exit code: !RC!
echo Log: %STARTUP_LOG%
call :log failure "classification=DEPENDENCY_INSTALL_FAILED exit_code=!RC!"
pause
exit /b 1

:fastapi_failed
echo [FundTrace] ERROR: FundTrace service failed to start.
echo Exit code: !RC!
echo Log: %STARTUP_LOG%
call :log failure "classification=FASTAPI_START_FAILED exit_code=!RC!"
pause
exit /b 1
