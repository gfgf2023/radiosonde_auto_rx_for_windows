# RTL-TCP Time-Slicing Implementation Status

Status: Complete for the 1.9.0-beta21 Windows release.

## Delivered

- `autorx/time_slice.py` implements the single-tuner scheduler, fair candidate
  rotation, scan generations, slice IDs, stale event rejection, manual
  candidate priority, and 10/15/25 second timing boundaries.
- Configuration defaults and validation require one `RTL_TCP` tuner, reject
  `always_decode`, reject invalid or non-finite timeouts, and leave the feature
  disabled for existing configurations.
- `SondeScanner` reports complete scan cycles and reuses only candidates that
  have produced valid telemetry. Every fourth scan generation revalidates
  candidate types so a different sonde on the same frequency can be found.
- `SondeDecoder` reports valid filtered frames and supports a bounded stop. A
  stuck decoder is force-terminated rather than freezing the complete rotation.
- The main task manager executes atomic scheduler action batches, validates
  slice IDs before starting decoders, releases the old tuner owner before
  starting the next task, pauses starts while scanning is disabled, and clears
  pending actions during shutdown.
- The Web interface exposes status, current/next frequency, rotation progress,
  remaining time, authenticated Skip and Rescan controls, and manual candidate
  insertion with sonde-type validation.
- Known candidates survive one missed complete scan and are removed after two.
  Decode failures do not create interference blocks or permanent bans.

## Compatibility

When `time_slice_enabled = False`, scanner callbacks, decoder lifetimes, task
allocation, and Web controls use the existing behavior. The mode can only be
enabled with `sdr_type = RTL_TCP`, `sdr_quantity = 1`, and `always_decode = []`.

## Verification

- Pure scheduler tests cover one, four, and eight candidates, new-candidate
  priority, fair rotations, timeout boundaries, missed scans, stale events,
  manual controls, and configuration validation.
- Integration tests cover scan-cycle callbacks, known-frequency matching,
  decoder valid-frame callbacks, atomic and stale action handling, empty-scan
  restarts, pause/resume behavior, bounded decoder shutdown, Web authorization,
  manual type validation, and disabled status.
- The full Python suite and native Windows build are required immediately
  before publishing beta21.

Hardware validation with a live RTL-TCP server and several simultaneous sondes
remains an operational post-release check; it is not simulated by the unit test
suite.
