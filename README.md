![auto_rx logo](autorx.png)
# Automatic Radiosonde Receiver Utilities

**Please refer to the [auto_rx wiki](https://github.com/projecthorus/radiosonde_auto_rx/wiki) for the latest information.**

This project is built around [rs1729's RS](https://github.com/rs1729/RS) demodulators, and provides a set of utilities ('auto_rx') to allow automatic reception and uploading of [Radiosonde](https://en.wikipedia.org/wiki/Radiosonde) positions to multiple services, including:

* The [SondeHub Radiosonde Tracker](https://tracker.sondehub.org) - a tracking website specifically designed for tracking radiosondes!
* APRS-IS, for display on sites such as [radiosondy.info](https://radiosondy.info). (Note that aprs.fi now blocks radiosonde traffic.)
* [ChaseMapper](https://github.com/projecthorus/chasemapper) for mobile
  radiosonde chasing.

Auto-RX's [Web Interface](https://github.com/projecthorus/radiosonde_auto_rx/wiki/Web-Interface-Guide) provides a way of seeing the live status of your station, and also a means of reviewing and analysing previous radiosonde flights. Collected meteorological data can be plotted in the common 'Skew-T' format.

### Radiosonde Support Matrix

Manufacturer | Model | Position | Temperature | Humidity | Pressure | XDATA
-------------|-------|----------|-------------|----------|----------|------
Vaisala | RS92-SGP/NGP | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark:
Vaisala | RS41-SG/SGP/SGM | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: (for -SGP) | :heavy_check_mark:
Graw | DFM06/09/17 | :heavy_check_mark: | :heavy_check_mark: | :x: | :x: | :heavy_check_mark:
Meteomodem | M10 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | Not Sent | :x:
Meteomodem | M20 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: (For some models) | :x:
Intermet Systems | iMet-4 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark:
Intermet Systems | iMet-54 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | Not Sent | :x:
Lockheed Martin | LMS6-400/1680 | :heavy_check_mark: | :x: | :x: | :x: | Not Sent
Meisei | iMS-100 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :x: | Not Sent
Meisei | RS11G | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :x: | Not Sent
Meteo-Radiy | MRZ-H1 (400 MHz) | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :x: | Not Sent
Meteosis | MTS01 | :heavy_check_mark: | :heavy_check_mark: | :x: | :x: | Not Sent
Changfeng | CF-06 | :heavy_check_mark: | :heavy_check_mark: | :x: | :x: | Not Sent
Changwang | GTH-6 | :heavy_check_mark: | :heavy_check_mark: | :x: | :x: | Not Sent
Meteolabor | SRS-C50 | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :x:

Support for other radiosondes may be added as required - please send us sondes to test with! If you have any information about telemetry formats, we'd love to hear from you (see our contact details below).

Improvements from the upstream RS codebase will be merged into this codebase when/where appropriate. A big thanks to rs1729 for continuing to develop and improve these decoders, and working with us to make auto_rx decode *all* the radiosondes!

### Updates

**This software is under regular development. Please [update regularly](https://github.com/projecthorus/radiosonde_auto_rx/wiki/Performing-Updates) to get bug-fixes and improvements!**

Please consider joining the Google Group to receive updates on new software features:
https://groups.google.com/forum/#!forum/radiosonde_auto_rx

We also have a channel in the SondeHub Discord server: https://sondehub.org/go/discord

## Presentations
* Linux.conf.au 2019 - https://www.youtube.com/watch?v=YBy-bXEWZeM
* UKHAS Conference 2019 - [Presented via Skype](https://youtu.be/azDJmMywBgw?t=643) which had some audio issues at the start. Slides [here](https://rfhead.net/sondes/auto_rx_presentation_UKHAS2019.pdf).

## Contacts
* [Mark Jessop](https://github.com/darksidelemm) - vk5qi@rfhead.net
* [Michaela Wheeler](https://github.com/TheSkorm) - radiosonde@michaela.lgbt

## Windows Build and Run

The native Windows x64 release is built with MinGW-w64. Install a MinGW-w64
toolchain that provides `x86_64-w64-mingw32-gcc` and `mingw32-make`, plus
Python 3. Put the Windows RTL-SDR tools `rtl_fm.exe`, `rtl_power.exe`,
`rtl_sdr.exe`, and `sox.exe`, plus `rtlsdr.dll`, `libusb-1.0.dll`, and every
other DLL they require, in
`third_party/windows/bin/`. This directory is deliberately an external input:
the packager copies its available contents but refuses to create an incomplete
release when a required executable or RTL-SDR runtime DLL is missing.

From PowerShell, build the ZIP with:

```powershell
.\build-windows.ps1
```

Use `-Version 1.9.0-beta17`, `-MakeCommand`, or `-Compiler` when the local tool
names differ. The resulting `release/windows/auto_rx-windows-<version>.zip`
contains `auto_rx/`, the 18 decoder executables and receiver tools in `bin/`,
plus `start-auto-rx.cmd` and `diagnose.cmd`. Pass `-KeepRelease` to retain the
unpacked staging directory as well as the ZIP. `-ValidateOnly` checks only the
third-party tool input and is useful in CI.

Extract the ZIP, run `start-auto-rx.cmd`, then edit the generated
`auto_rx/station.cfg` before receiving. It creates a Python virtual environment
and installs the application requirements on its first run. It requires the
Windows Python launcher to provide `py -3`. Run `diagnose.cmd` to check the
packaged tools and Python before starting; it does not require a connected SDR.

The generated configuration defaults to a locally connected USB receiver:

```ini
[sdr]
sdr_type = RTLSDR
```

Connect an RTL-SDR, ensure no other program owns it, and keep this setting to
use the local receiver. A startup error such as `RTLSDR 1 config - SDR
unresponsive` means that the local `rtl_sdr` probe could not access the device;
it does not indicate that the packaged programs are missing.

To receive from an existing `rtl_tcp` server instead, edit the `[sdr]` section
and retain exactly one `[sdr_1]` receiver section:

```ini
[sdr]
sdr_type = RTL_TCP
sdr_quantity = 1
sdr_hostname = 192.0.2.10
sdr_port = 1234

[sdr_1]
ppm = 0
gain = -1
bias = False
```

Replace `192.0.2.10` and `1234` with the reachable RTL-TCP host and port, then
start `rtl_tcp` on that server before running `start-auto-rx.cmd`. Standard
RTL-TCP exposes one physical tuner, so `sdr_quantity` must be `1`, and Bias-T
must remain disabled. The Windows release scans and decodes using the configured
RTL-TCP endpoint; it does not need a locally attached RTL-SDR in this mode.
Set `gain = -1` to use the tuner's automatic gain control, set a non-negative
value for a fixed gain in dB, or use `gain = -2` to additionally enable the
standard RTL-TCP baseband AGC command.

The release requests an RTL-SDR-compatible hardware IQ rate from the RTL-TCP
server, then uses its local `iq_dec` program to resample for each decoder. Do
not try to lower the server rate to a decoder rate such as `48000`; the release
handles that conversion and avoids the server's invalid-sample-rate error.
The RTL-TCP decoder bridge permits up to 60 seconds for the first or subsequent
IQ data after tuning, so a short server retune delay does not stop decoding.
Native Windows decoder programs also read IQ and audio pipelines in binary mode,
preventing Windows text-mode control bytes from terminating a decoder stream.
GTH/CF6 decoding and 400 MHz type detection consume the supported 240 kHz
RTL-TCP stream directly and use their native decimators, avoiding an extra
filtering stage on narrow GFSK signals.
The GTH/CF6 detector uses the decoder's complete synchronization profile so
automatically scanned GTH signals can transition into decoding without a
manual web request.

When using the web interface's manual decoder control, enter a positive finite
frequency in Hz, for example `401500000`. Invalid values such as `nan` are
rejected without interrupting the scanner or running decoders.

## Licensing Information
All software within this repository is licensed under the GNU General Public License v3. Refer to the LICENSE file for the full license text.

Radiosonde telemetry data captured via this software and uploaded into the [Sondehub](https://sondehub.org/) Database system is licensed under [Creative Commons BY-SA v2.0](https://creativecommons.org/licenses/by-sa/2.0/). 
Telemetry data uploaded into the APRS-IS network is generally considered to be released into the public domain. 

By uploading data into these systems (by enabling the relevant uploaders within the `station.cfg` file) you as the user agree for your data to be made available under these licenses. Note that uploading to Sondehub is enabled by default.
