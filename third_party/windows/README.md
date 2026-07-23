# Windows Third-Party Binaries

Place distributable Windows x64 receiver tools in `bin/` before running
`build-windows.ps1`:

- `rtl_fm.exe`
- `rtl_power.exe`
- `sox.exe`

Include every DLL needed by those executables in the same directory. The build
copies all available files from `third_party/windows/bin/` into the release
`bin/` directory, but stops before compilation if any required executable is
missing. This keeps externally supplied binary licenses and provenance outside
the source tree while preventing a release that cannot receive from RTL-SDR.
