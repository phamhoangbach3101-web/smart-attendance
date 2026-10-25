@echo off
chcp 65001 >nul
REM Cai dat Smart Attendance (chay mot lan)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
