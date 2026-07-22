# Native Windows RTL-SDR and RTL-TCP Port

## Goal

Run the complete auto_rx receiver natively on Windows 10/11 x64. The first
hardware target is a locally attached RTL-SDR. The port also supports a remote
standard `rtl_tcp` server for scanning and decoding. Existing Linux behavior
and the SpyServer and KA9Q interfaces remain intact.

## Platform Boundary

Add an `autorx.platform` module as the only Windows-specific boundary. It
provides executable resolution, a null device, command execution with Python
timeouts, pipeline startup, process-tree termination, and USB reset handling.

On Windows it resolves decoder and tool names with `.exe`, uses `NUL` for
discarded output, starts pipeline processes in a new process group, and stops
them through `taskkill /T /F`. It does not require the Unix `timeout` command.
USB reset is reported as unavailable rather than preventing reception. Linux
keeps the existing command and process behavior.

`decode.py`, `scan.py`, and `sdr_wrappers.py` use this boundary rather than
direct Unix process primitives. Command text may continue to represent a
pipeline, but Windows redirects are converted to CMD syntax and timeout is
enforced by Python.

## RTL-SDR Support

The Windows release contains the auto_rx decoder executables, `rtl_fm.exe`,
`rtl_power.exe`, and `sox.exe` in `bin/`. A Windows configuration defaults to
the RTLSDR input and supports explicit tool paths. Startup validation reports
missing executables and invalid device configuration before receiver threads
start.

## RTL-TCP Support

Add `sdr_type = RTL_TCP` with host, port (default 1234), sample rate, PPM, and
gain settings. `rtl_tcp_client.py` implements the standard protocol handshake,
tuning commands, IQ reads, timeouts, and controlled reconnects.

`rtl_tcp_rx.py` adapts unsigned 8-bit RTL-TCP IQ into signed 16-bit IQ for the
existing decoder chain. FM processing uses `iq_dec --FM` instead of `rtl_fm`.
An RTL-TCP scanner captures each required spectrum segment, calculates power
with NumPy, and exposes the result in the same form consumed by the existing
scanner. This preserves the full scan, allocate, decode workflow without
`rtl_power.exe`.

Only standard RTL-TCP control commands are assumed. Bias-T is not enabled for
RTL-TCP because support is not part of the base protocol. Connection, tune, and
read failures release the current task and retry on a later scan cycle.

## Distribution

Ship an unpacked Windows x64 release containing:

- `auto_rx/` with the application and web assets.
- `bin/` with decoders and third-party receiver tools.
- `start-auto-rx.cmd` to create or use a virtual environment, install pinned
  dependencies, validate tools, and start the application.
- `diagnose.cmd` for environment, binary, and SDR connectivity checks.
- `station.cfg.example.windows` with RTLSDR and RTL_TCP examples.

Windows does not provide a systemd unit. Users can run the command script,
use Task Scheduler, or add a service wrapper separately.

## Validation

Automated Windows tests cover full module import, command translation,
executable discovery, process cleanup, configuration parsing, and the RTL-TCP
handshake, command bytes, IQ conversion, scanning segments, and reconnects
using a local fake server.

Integration tests start the web service and execute a scan-to-decode flow with
recorded IQ or fake receiver tools. Hardware acceptance verifies local RTL-SDR
and RTL-TCP inputs can detect devices, scan, decode one supported sonde, and
write telemetry logs with upload disabled.
