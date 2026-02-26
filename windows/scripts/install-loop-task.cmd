@echo off
setlocal

REM ============================================================
REM  One-click installer for the GlobalBackground 24-hour
REM  animated wallpaper loop.
REM
REM  Double-click this file to:
REM    1. Auto-detect screen resolution and patch config.toml
REM    2. Auto-detect Python (3.11+) and install Pillow
REM    3. Register a "run at logon" Scheduled Task
REM    4. Start the loop immediately (backfills 24 hourly frames,
REM       then plays them as a cycling wallpaper slideshow)
REM
REM  To stop:      windows\scripts\stop-loop-task.ps1
REM  To uninstall: windows\scripts\uninstall-loop-task.ps1
REM  Logs:         logs\loop.log
REM ============================================================

echo.
echo === GlobalBackground: 24-hour Animated Wallpaper Installer ===
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-loop-task.ps1" -ConfigPath "config.toml" -RunNow %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed. See above for details.
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Installed. The animated wallpaper loop is now running.
echo     Check logs\loop.log for progress.
echo.
pause
