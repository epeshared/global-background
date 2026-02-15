@echo off
setlocal

REM One-click installer for the hourly scheduled task.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-hourly-task.ps1" %*

endlocal
