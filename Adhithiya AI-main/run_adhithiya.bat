@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.12"
    if not defined PY_CMD (
        py -3.11 -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3.11"
    )
    if not defined PY_CMD (
        py -3.13 -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=py -3.13"
    )
)
if not defined PY_CMD (
    python -c "import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python 3.11, 3.12, or 3.13 was not found.
    echo Install 64-bit Python from https://www.python.org/downloads/windows/
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
"%VENV_PY%" -c "import struct, sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 (
    echo [ADHITHIYA] The existing environment uses an unsupported Python. Rebuilding it...
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
echo Check that Python 3.11-3.13 and the Windows audio drivers are installed.
pause
exit /b 1
