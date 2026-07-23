@echo off
setlocal
set "ROOT=%~dp0"
set "PATH=%ROOT%bin;%PATH%"

if not exist "%ROOT%auto_rx\station.cfg" (
    copy /Y "%ROOT%auto_rx\station.cfg.example.windows" "%ROOT%auto_rx\station.cfg" >NUL
    echo Created auto_rx\station.cfg from the Windows example. Edit station location and SDR settings before use.
)

call "%ROOT%diagnose.cmd"
if errorlevel 1 exit /b 1

where py >NUL 2>NUL
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >NUL 2>NUL
    if errorlevel 1 (
        echo Python 3 was not found. Install Python 3.10 or newer and run this script again.
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist "%ROOT%.venv\Scripts\python.exe" (
    %PYTHON% -m venv "%ROOT%.venv"
    if errorlevel 1 exit /b 1
    "%ROOT%.venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    "%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%auto_rx\requirements.txt"
    if errorlevel 1 exit /b 1
)

pushd "%ROOT%auto_rx"
"%ROOT%.venv\Scripts\python.exe" auto_rx.py -c station.cfg
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
