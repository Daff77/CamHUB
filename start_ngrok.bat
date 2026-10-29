@echo off
title CamHUB Ngrok Tunnel Launcher
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_ngrok.ps1"
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo [ERROR] Ngrok exited with error code %ERRORLEVEL%.
  pause
)
