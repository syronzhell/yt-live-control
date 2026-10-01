@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        py -3 server.py
        goto finish
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        python server.py
        goto finish
    )
)
echo Python 3.10 atau lebih baru belum ditemukan.
echo Install Python resmi untuk Windows, lalu jalankan START.bat lagi.
echo Saat instalasi, aktifkan Add Python to PATH.
start "" "https://www.python.org/downloads/windows/"
:finish
echo.
echo Jika program berhenti karena error, baca pesan di atas.
pause
