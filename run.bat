@echo off
REM Version: V26.281.1108
REM Double-click to start LunarReef and open it in your browser.
cd /d "%~dp0"
python -m lunarreef web %*
pause
