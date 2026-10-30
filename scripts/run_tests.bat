@echo off
title CamHUB Test Runner
cd /d "%~dp0.."
echo ==================================================
echo               Running CamHUB Tests                
echo ==================================================
echo.
python -m unittest discover -s tests -v
echo.
pause

