@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /i not "%OS%"=="Windows_NT" (
    echo [ERROR] This builder must be run on Windows. PyInstaller cannot cross-build a Windows executable from macOS or Linux.
    pause
    exit /b 1
)

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
    echo [ERROR] A 64-bit Python installation is required to build the Windows executable.
    pause
    exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
    echo [ADHITHIYA] Creating the Windows build environment...
    %PY_CMD% -m venv .venv-build
    if errorlevel 1 goto :failed
)

set "BUILD_PY=%CD%\.venv-build\Scripts\python.exe"
"%BUILD_PY%" -c "import struct, sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 14) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 (
    echo [ADHITHIYA] Rebuilding an incompatible build environment...
    rmdir /s /q .venv-build
    %PY_CMD% -m venv .venv-build
    if errorlevel 1 goto :failed
)

echo [ADHITHIYA] Installing app and packaging dependencies...
"%BUILD_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%BUILD_PY%" -m pip install -r requirements.txt pyinstaller faster-whisper
if errorlevel 1 goto :failed

echo [ADHITHIYA] Building the standalone Windows executable...
"%BUILD_PY%" -m PyInstaller ADHITHIYA-windows.spec --noconfirm --clean
if errorlevel 1 goto :failed

if not exist "dist\ADHITHIYA.exe" (
    echo [ERROR] PyInstaller finished but dist\ADHITHIYA.exe was not created.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Windows executable created:
echo           %CD%\dist\ADHITHIYA.exe
echo.
echo The executable bundles the app and offline Whisper code. The built-in brain downloads to %%USERPROFILE%%\.adhithiya; Whisper weights use the Hugging Face cache.
echo You can copy ADHITHIYA.exe to another Windows 10/11 64-bit computer; Python is not required there.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] The Windows build failed. Review the error above and verify Python 3.11-3.13 is installed.
pause
exit /b 1
