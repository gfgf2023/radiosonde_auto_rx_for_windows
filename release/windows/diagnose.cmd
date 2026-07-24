@echo off
setlocal
set "ROOT=%~dp0"
set "PATH=%ROOT%bin;%PATH%"
set "FAILED=0"

for %%F in (rtl_fm.exe rtl_power.exe rtl_sdr.exe sox.exe librtlsdr.dll libusb-1.0.dll dft_detect.exe fsk_demod.exe imet4iq.exe mk2a1680mod.exe rs41mod.exe dfm09mod.exe m10m20mod.exe rs92mod.exe lms6Xmod.exe meisei100mod.exe imet54mod.exe mp3h1mod.exe mts01mod.exe cf06ht03mod.exe c50iq.exe iq_dec.exe weathex301d.exe rd94rd41drop.exe) do (
    if not exist "%ROOT%bin\%%F" (
        echo MISSING: bin\%%F
        set "FAILED=1"
    )
)

py -3 --version >NUL 2>NUL
if errorlevel 1 (
    echo MISSING: Python launcher with Python 3 ^(py -3^)
    set "FAILED=1"
)

if "%FAILED%"=="1" (
    echo Diagnosis failed. Install the listed dependency or rebuild the release.
    exit /b 1
)

echo All packaged receiver tools and Python 3 are available.
echo Connect a local RTL-SDR and use RTLSDR in station.cfg, or point RTL_TCP at a reachable server.
exit /b 0
