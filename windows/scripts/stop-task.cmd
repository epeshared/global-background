@echo off
setlocal

REM One-click script to stop the scheduled task (end running instance).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-task.ps1" %*

endlocal
