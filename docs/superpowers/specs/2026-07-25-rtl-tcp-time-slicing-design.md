# RTL-TCP Time-Sliced Radiosonde Reception Design

## Context

The Windows port supports a standard RTL-TCP endpoint, but the protocol exposes
one global tuner. A single endpoint therefore cannot scan while a decoder owns
the tuner, and it cannot decode several frequencies concurrently. In areas with
four to eight active radiosondes, the existing lock-on behavior can leave every
signal except the first one unobserved until that decoder times out.

This design adds opt-in time-sliced reception for one RTL-TCP tuner. It retains
the existing scanner and decoder implementations, and adds a scheduler that
alternates between discovery scans and bounded decoder slices.

## Goals

- Refresh four to eight confirmed radiosondes in approximately three minutes.
- Give each frequency enough time to acquire and decode several valid frames.
- Rescan after every complete rotation so new signals are discovered promptly.
- Preserve fair access while giving newly discovered signals one prompt trial.
- Expose rotation status and immediate skip/rescan controls in the web UI.
- Leave all behavior unchanged when time slicing is disabled.

## Non-Goals

- Concurrent decoding from one RTL-TCP endpoint.
- Interference scoring, automatic blacklisting, failure counters, or automatic
  frequency blocking.
- Support for time slicing across multiple local RTL-SDR devices or KA9Q
  channels in this iteration.
- Persistent scheduler state across application restarts.

## Configuration

The following options are added to the `[advanced]` section:

```ini
time_slice_enabled = False
time_slice_acquire_timeout = 10
time_slice_decode_time = 15
time_slice_hard_limit = 25
```

The default remains disabled for compatibility. Validation rejects non-positive
durations, a hard limit shorter than the acquisition and decode budgets added
together, and an enabled mode
unless `sdr_type = RTL_TCP` and `sdr_quantity = 1`.
An enabled mode also rejects a non-empty `always_decode` list because an
always-on decoder would permanently own the single tuner.

The documented configuration for the intended receiver sets
`time_slice_enabled = True`. Existing `only_scan`, `always_scan`, `never_scan`,
`max_peaks`, quantization, gain, PPM, and scan range options continue to apply.

## Components

### TimeSliceScheduler

A new `autorx.time_slice` module owns scheduling policy without opening SDRs or
starting subprocesses. Its public operations accept scan detections, scan-cycle
completion, valid decoder frames, decoder completion, elapsed time, and web
control requests. It returns explicit actions for the task manager:

- start or stop a discovery scan;
- start or stop a decoder at a frequency and sonde type;
- skip the current candidate;
- begin a fresh scan.

The scheduler uses a lock because scan and decoder callbacks originate from
worker threads while task actions run in the main loop.

### Candidate Registry

Each quantized frequency has one candidate record containing:

- frequency and detected sonde type;
- first and most recent scan generation in which it was seen;
- first and most recent valid telemetry time;
- whether it has ever produced a valid frame;
- the most recent rotation in which it was served;
- current state: new, acquiring, confirmed, waiting, or stale.

There is deliberately no failure count or blocked state. A trial that produces
no valid frame ends normally and remains eligible when the frequency appears in
a future scan.

New detections are tried once before previously confirmed candidates resume
round-robin order. Confirmed candidates are otherwise ordered by the oldest
`last_served` value, which prevents starvation.

### Scanner Integration

`SondeScanner` gains an optional scan-cycle completion callback and an optional
known-candidate lookup. Existing callbacks remain unchanged outside time-slice
mode.

During a time-slice discovery cycle:

1. The normal RTL-TCP PSD scan produces quantized peaks.
2. A peak matching a known candidate reuses its known sonde type and does not
   repeat the expensive type detector.
3. A new peak follows the existing `dft_detect` and GTH CRC fallback path.
4. Confirmed detections are sent to the scheduler as they are found.
5. When all peaks have been processed, the scanner emits one cycle-complete
   event containing the final detection set and scan generation.

The task manager does not stop the scanner on the first result in time-slice
mode. It waits for cycle completion, stops and releases the scanner, then starts
the next decoder selected by the scheduler.

Candidates that are absent from two consecutive complete PSD scans are removed.
One missed scan only marks a candidate stale, allowing for fading or a brief
scan miss. A type detected at the same quantized frequency replaces the prior
type and is treated as a new candidate.

### Decoder Integration

`SondeDecoder` exposes valid-frame timing to the scheduler. A decoder slice has
three boundaries:

- acquisition timeout: stop after 10 seconds if no valid JSON frame arrived;
- useful decode time: after the first valid frame, continue for 15 seconds;
- hard limit: stop after 25 seconds from process start under all conditions.

The first boundary that is reached ends the slice. A valid frame promotes the
candidate to confirmed and updates its last-success time. Ending a slice does
not use the existing temporary-lockout exit state and never modifies
`never_scan` or the temporary block list.

After cleanup releases the RTL-TCP tuner, the scheduler starts the next eligible
candidate directly. After every candidate in the current rotation has been
served, it requests a new discovery scan.

## State Machine

The scheduler has four top-level states:

1. `SCANNING`: collect a complete discovery cycle; do not start decoders.
2. `ACQUIRING`: a decoder is running but has not emitted a valid frame.
3. `DECODING`: at least one valid frame arrived; run the useful decode budget.
4. `TRANSITION`: wait for scanner or decoder cleanup before issuing the next
   tuner-owning action.

Only the task manager executes actions, so the scanner and decoder can never own
the single RTL-TCP tuner at the same time. Duplicate completion events and late
worker callbacks are ignored using monotonically increasing scan and slice IDs.

## Timing and Capacity

For a healthy signal, acquisition is expected to take approximately one to
three seconds, followed by 15 seconds of useful decoding. Eight healthy signals
therefore consume roughly 128 to 144 seconds. One approximately 20-second PSD
scan plus transitions keeps the normal full rotation near 2.5 to 3 minutes.

An undecodable new signal consumes at most the 10-second acquisition budget in
that rotation. It is not retained in the confirmed queue unless it later emits
a valid frame, but it may be retried when rediscovered by the next full scan.

## Web Interface

The existing task area adds a compact time-slice status row showing:

- mode enabled/disabled;
- current frequency and state;
- next frequency;
- candidate count and rotation progress;
- seconds remaining in the current phase.

Two authenticated controls are added:

- skip the current slice and continue with the next candidate;
- stop the current slice and start a fresh discovery scan.

The controls request scheduler actions and never manipulate task dictionaries
from the Flask thread. Existing scanner and decoder controls continue to work;
a manual decoder start in time-slice mode adds or prioritizes that candidate for
the next available slice rather than creating an unbounded decoder.

## Error Handling

- SDR and process failures retain the existing reset and failed-SDR handling.
- A decoder process that exits early ends only its current slice.
- Stale or duplicate events cannot stop a newer scanner or decoder because every
  action carries its scan or slice ID.
- Disabling the scanner from the web pauses discovery and rotation after the
  current task is cleaned up. Re-enabling it starts a fresh scan.
- Application shutdown cancels scheduler actions before the existing task
  shutdown sequence.
- Invalid configuration prevents startup with a specific configuration error.

## Compatibility

When `time_slice_enabled = False`, `handle_scan_results`, `clean_task_list`,
`SondeScanner`, `SondeDecoder`, and all web controls follow their existing code
paths. The scheduler is created only for the supported one-tuner RTL-TCP mode.
No decoder command, sonde threshold, filter bandwidth, telemetry exporter, or
upload behavior changes.

## Testing

Pure scheduler tests use a fake monotonic clock and cover:

- one, four, and eight-candidate fair rotations;
- new-candidate priority without starvation;
- 10-second acquisition timeout;
- 15 seconds after the first valid frame;
- 25-second hard limit;
- rescanning after every complete rotation;
- one missed scan retained and two missed scans removed;
- undecodable candidates retried without blocking;
- stale callback and duplicate completion rejection;
- manual skip and immediate-rescan actions.

Integration tests cover task allocation, scanner cycle completion, decoder
valid-frame reporting, web authorization, status serialization, configuration
validation, and the unchanged disabled-mode behavior. The complete Python suite
and native Windows build must pass before a release package is produced.
