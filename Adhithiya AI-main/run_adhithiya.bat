@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.14 -c "import sys; sys.exit(not (sys.version_info[:2] == (3, 14) and sys.version_info >= (3, 14, 10)))" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.14"
)
if not defined PY_CMD (
    python -c "import sys; sys.exit(not (sys.version_info[:2] == (3, 14) and sys.version_info >= (3, 14, 10)))" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python 3.14.10 or a later 3.14 patch was not found.
    echo Install 64-bit Python 3.14.10 or later from https://www.python.org/downloads/windows/
    echo and enable the Python Launcher during setup, then run this file again.
    pause
    exit /b 1
)
%PY_CMD% -c "import struct, sys; sys.exit(struct.calcsize('P') != 8)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] A 64-bit Python installation is required.
    pause
    exit /b 1
)

echo [ADHITHIYA] Creating the Python environment if needed...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :failed
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
"%VENV_PY%" -c "import struct, sys; sys.exit(not (sys.version_info[:2] == (3, 14) and sys.version_info >= (3, 14, 10) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 (
    echo [ADHITHIYA] The existing environment is not a compatible Python 3.14.10+ environment. Rebuilding it...
    rmdir /s /q .venv
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :failed
)

"%VENV_PY%" -c "import openai, PyQt6, sounddevice" >nul 2>&1
if errorlevel 1 (
    echo [ADHITHIYA] Installing Python packages. This may take several minutes...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :failed
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
)

set "PYTHONUTF8=1"
echo [ADHITHIYA] Starting the Windows app...
"%VENV_PY%" main.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo [ERROR] ADHITHIYA did not start. The error details are shown above.
echo Check that 64-bit Python 3.14.10+ and the Windows audio drivers are installed.
pause
exit /b 1
