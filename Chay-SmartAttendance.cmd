@echo off
chcp 65001 >nul
REM Khoi dong Smart Attendance (web) - mo http://127.0.0.1:8000
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
