@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 server.py --demo --port 8766
) else (
    python server.py --demo --port 8766
)
pause
