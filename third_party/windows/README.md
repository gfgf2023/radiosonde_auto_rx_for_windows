# Windows Third-Party Binaries

Place distributable Windows x64 receiver tools in `bin/` before running
`build-windows.ps1`:

- `rtl_fm.exe`
- `rtl_power.exe`
- `rtl_sdr.exe`
- `sox.exe`

Include `librtlsdr.dll`, `libusb-1.0.dll`, and every other DLL needed by those
executables in the same directory. The build copies all available files from
`third_party/windows/bin/` into the release `bin/` directory, but stops before
compilation if a required executable or the RTL-SDR runtime DLLs are missing.
This keeps externally supplied binary licenses and provenance outside the
source tree while preventing a release that cannot receive from RTL-SDR.
