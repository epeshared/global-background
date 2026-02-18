@echo off
setlocal

REM ============================================================
REM  One-click installer for the GlobalBackground hourly task.
REM  Double-click this file to:
REM    1. Auto-detect Python with Pillow
REM    2. Install a Windows Scheduled Task (every 60 min)
REM    3. Immediately run the first update
REM ============================================================

echo.
echo === GlobalBackground: One-Click Install ===
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-hourly-task.ps1" -ConfigPath "config.toml" -RunNow %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed. See above for details.
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Scheduled task installed and first run triggered.
echo     Wallpaper will auto-update every hour.
echo.
pause

endlocal
