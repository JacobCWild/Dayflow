@echo off
:: Dayflow for Windows – launcher
:: Double-click this file or run it from a Command Prompt to start Dayflow.

setlocal

:: ── Check Python ──────────────────────────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python is not installed or not on PATH.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ── Install / upgrade dependencies (silent on subsequent runs) ────────────
echo Installing / checking dependencies...
python -m pip install -q -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: ── Start Dayflow ─────────────────────────────────────────────────────────
echo Starting Dayflow...
python "%~dp0dayflow.py" %*

:: Keep the window open if the script exits with an error
if %ERRORLEVEL% NEQ 0 pause
