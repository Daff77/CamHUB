@echo off
title CamHUB Host Server
cd /d "%~dp0.."
echo ==================================================
echo              Starting CamHUB Server               
echo ==================================================
echo.
python -u server.py --port 3000
pause

