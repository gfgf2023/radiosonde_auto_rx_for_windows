"""Time-sliced RTL-TCP scheduler for radiosonde_auto_rx.

A single RTL-TCP endpoint exposes one global tuner, so it cannot scan and
decode simultaneously.  This module implements the scheduling policy that
alternates discovery scans with bounded decoder slices, allowing four to eight
active radiosondes to be served in roughly three minutes.

The scheduler has no SDR access and starts no subprocesses.  All state changes
are driven by events (scan detections, cycle completion, valid decoder frames,
decoder exit) plus periodic clock ticks.  Each public method returns a list of
``SchedulerAction`` objects for the caller (task manager) to execute.

This module is only instantiated when ``time_slice_enabled = True`` and
``sdr_type = RTL_TCP`` with ``sdr_quantity = 1``.  When disabled, all existing
code paths are unchanged.
"""

import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------

class CandidateState(Enum):
    """Lifecycle state of one candidate frequency."""
    NEW = "new"
    ACQUIRING = "acquiring"
    CONFIRMED = "confirmed"
    WAITING = "waiting"
    STALE = "stale"


class SchedulerState(Enum):
    """Top-level state of the time-slice scheduler."""
    SCANNING = "scanning"
    ACQUIRING = "acquiring"
    DECODING = "decoding"
    TRANSITION = "transition"


class ActionKind(Enum):
    """Type of action the task manager must execute."""
    START_SCAN = "start_scan"
    STOP_SCAN = "stop_scan"
    START_DECODER = "start_decoder"
    STOP_DECODER = "stop_decoder"
    NONE = "none"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SchedulerAction:
    """An instruction returned to the task manager."""
    kind: ActionKind
    frequency: Optional[int] = None
    sonde_type: Optional[str] = None
    slice_id: Optional[int] = None

    def __repr__(self) -> str:
        parts = [f"kind={self.kind.value}"]
        if self.frequency is not None:
            parts.append(f"freq={self.frequency}")
        if self.sonde_type is not None:
            parts.append(f"type={self.sonde_type}")
        if self.slice_id is not None:
            parts.append(f"slice={self.slice_id}")
        return f"SchedulerAction({', '.join(parts)})"


@dataclass
class CandidateRecord:
    """All known information about one quantized candidate frequency."""
    frequency: int
    sonde_type: str
    first_scan_gen: int
    last_scan_gen: int
    state: CandidateState = CandidateState.NEW
    first_valid_frame_time: Optional[float] = None
    last_valid_frame_time: Optional[float] = None
    ever_produced_valid_frame: bool = False
    last_served_rotation: int = -1
    _consecutive_misses: int = field(default=0, repr=False)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class TimeSliceScheduler:
    """Schedule discovery scans and bounded decoder slices over one RTL-TCP tuner.

    Args:
        acquire_timeout: Seconds to wait for the first valid frame before
            abandoning a slice.  Defaults to 10.
        decode_time: Seconds of useful decode time after the first valid frame.
            Defaults to 15.
        hard_limit: Maximum seconds a decoder may run regardless of frame
            activity.  Must be >= acquire_timeout + decode_time.  Defaults
            to 25.
        clock: A zero-argument callable returning the current monotonic time.
            Defaults to ``time.monotonic``.  Supply a fake for unit tests.
    """

    def __init__(
        self,
        acquire_timeout: float = 10.0,
        decode_time: float = 15.0,
        hard_limit: float = 25.0,
        clock=None,
    ):
        if acquire_timeout <= 0:
            raise ValueError("acquire_timeout must be positive")
        if decode_time <= 0:
            raise ValueError("decode_time must be positive")
        if hard_limit < acquire_timeout + decode_time:
            raise ValueError(
                "hard_limit must be >= acquire_timeout + decode_time"
            )
        import time as _time_mod
        self._acquire_timeout = acquire_timeout
        self._decode_time = decode_time
        self._hard_limit = hard_limit
        self._clock = clock if clock is not None else _time_mod.monotonic

        self._lock = threading.Lock()
        self._state = SchedulerState.SCANNING

        # Candidate registry: quantized_freq -> CandidateRecord
        self._candidates: Dict[int, CandidateRecord] = {}

        # Monotonically increasing IDs
        self._scan_gen: int = 0          # incremented per complete scan cycle
        self._next_slice_id: int = 1
        self._current_slice_id: int = 0  # 0 = no active slice

        # Rotation counter: incremented after every full round of confirmed candidates
        self._rotation: int = 0

        # Active decoder state
        self._decoder_start_time: Optional[float] = None
        self._first_valid_frame_time: Optional[float] = None
        self._current_freq: Optional[int] = None
        self._current_sonde_type: Optional[str] = None

        # NEW candidates that have been picked for a trial but not yet served
        # (used to avoid re-picking the same new candidate twice in one rotation)
        self._new_candidate_served_this_rotation: set = set()

        # Whether a rescan was requested via web control
        self._rescan_requested: bool = False

    # ------------------------------------------------------------------
    # Event callbacks (called from worker threads)
    # ------------------------------------------------------------------

    def on_scan_detection(
        self, frequency: int, sonde_type: str, scan_gen: int
    ) -> List[SchedulerAction]:
        """Report one peak detection from the ongoing PSD scan.

        The scan calls this for each quantized peak as it is identified.
        Known candidates skip the expensive dft_detect step (the scanner
        owns that logic; we just update our registry here).

        Returns an empty list; no actions are needed per-detection.
        """
        with self._lock:
            if scan_gen != self._scan_gen:
                # Stale event from a previous scan generation — ignore.
                return []
            self._upsert_candidate(frequency, sonde_type, scan_gen)
            return []

    def add_candidate(self, frequency: int, sonde_type: str) -> List[SchedulerAction]:
        """Add or refresh a manually requested candidate.

        Manual requests join the normal candidate queue.  A running scan or
        decoder is not interrupted, so the single RTL-TCP tuner keeps one
        owner at a time.
        """
        with self._lock:
            frequency = int(frequency)
            self._upsert_candidate(frequency, str(sonde_type), self._scan_gen)
            if frequency != self._current_freq:
                record = self._candidates[frequency]
                record.state = CandidateState.NEW
                record.first_scan_gen = -1
                self._new_candidate_served_this_rotation.discard(frequency)
            return []

    def on_scan_cycle_complete(
        self, seen_frequencies: List[int], scan_gen: int
    ) -> List[SchedulerAction]:
        """Report that the scanner has finished one full PSD cycle.

        ``seen_frequencies`` is the list of all quantized frequencies that
        produced a confirmed detection in this cycle.  Candidates absent
        from this list accumulate missed-scan counts.

        Returns the actions the task manager should execute next.
        """
        with self._lock:
            if scan_gen != self._scan_gen:
                return []
            if self._state != SchedulerState.SCANNING:
                # Late completion event after we already moved on.
                return []

            seen_set = set(seen_frequencies)
            to_remove = []
            for freq, rec in self._candidates.items():
                if freq in seen_set:
                    rec._consecutive_misses = 0
                    if rec.state == CandidateState.STALE:
                        # Recovered from stale — promote back appropriately.
                        rec.state = (
                            CandidateState.CONFIRMED
                            if rec.ever_produced_valid_frame
                            else CandidateState.NEW
                        )
                else:
                    rec._consecutive_misses += 1
                    if rec._consecutive_misses >= 2:
                        to_remove.append(freq)
                    elif rec.state not in (
                        CandidateState.ACQUIRING,
                        CandidateState.STALE,
                    ):
                        rec.state = CandidateState.STALE

            for freq in to_remove:
                logging.debug(
                    "TimeSlice - removing candidate %.3f MHz after 2 missed scans",
                    self._candidates[freq].frequency / 1e6,
                )
                del self._candidates[freq]

            # Advance scan generation so future detections from a stale scan are
            # rejected.
            self._scan_gen += 1

            return self._advance()

    def on_valid_frame(self, slice_id: int) -> List[SchedulerAction]:
        """Report that the active decoder emitted one valid JSON frame.

        Promotes the candidate to CONFIRMED and starts the useful-decode
        budget if this is the first frame in the slice.
        """
        with self._lock:
            if slice_id != self._current_slice_id:
                return []
            now = self._clock()
            if self._decoder_start_time is None:
                self._decoder_start_time = now
            if self._first_valid_frame_time is None:
                self._first_valid_frame_time = now
                self._state = SchedulerState.DECODING
                logging.debug(
                    "TimeSlice - first valid frame for slice %d at %.1f s",
                    slice_id,
                    now - (self._decoder_start_time or now),
                )
            if self._current_freq is not None:
                rec = self._candidates.get(self._current_freq)
                if rec is not None:
                    rec.ever_produced_valid_frame = True
                    rec.last_valid_frame_time = now
                    if rec.first_valid_frame_time is None:
                        rec.first_valid_frame_time = now
                    if rec.state in (
                        CandidateState.ACQUIRING,
                        CandidateState.NEW,
                    ):
                        rec.state = CandidateState.CONFIRMED
            return []

    def on_decoder_started(self, slice_id: int) -> List[SchedulerAction]:
        """Start timeout accounting when the decoder actually owns the tuner."""
        with self._lock:
            if slice_id != self._current_slice_id:
                return []
            self._decoder_start_time = self._clock()
            return []

    def on_decoder_complete(self, slice_id: int) -> List[SchedulerAction]:
        """Report that the decoder process has exited.

        Ends the current slice and selects the next action.
        """
        with self._lock:
            if slice_id != self._current_slice_id:
                # Stale completion from a previous slice — ignore.
                return []
            self._finish_current_slice()
            return self._advance()

    def tick(self, now: Optional[float] = None) -> List[SchedulerAction]:
        """Check timeout boundaries and return any triggered actions.

        Call this periodically (e.g. every second) from the task manager's
        main loop.  ``now`` defaults to the injected clock.
        """
        with self._lock:
            if now is None:
                now = self._clock()
            if self._state not in (
                SchedulerState.ACQUIRING,
                SchedulerState.DECODING,
            ):
                return []
            if self._decoder_start_time is None:
                return []

            elapsed = now - self._decoder_start_time

            # Hard limit always wins.
            if elapsed >= self._hard_limit:
                logging.debug(
                    "TimeSlice - hard limit reached at %.1f s for slice %d",
                    elapsed,
                    self._current_slice_id,
                )
                return self._stop_and_advance()

            if self._state == SchedulerState.ACQUIRING:
                if elapsed >= self._acquire_timeout:
                    logging.debug(
                        "TimeSlice - acquisition timeout at %.1f s for slice %d",
                        elapsed,
                        self._current_slice_id,
                    )
                    return self._stop_and_advance()

            elif self._state == SchedulerState.DECODING:
                if (
                    self._first_valid_frame_time is not None
                    and now - self._first_valid_frame_time >= self._decode_time
                ):
                    logging.debug(
                        "TimeSlice - decode budget exhausted at %.1f s for slice %d",
                        elapsed,
                        self._current_slice_id,
                    )
                    return self._stop_and_advance()

            return []

    # ------------------------------------------------------------------
    # Web control requests (called from Flask thread)
    # ------------------------------------------------------------------

    def skip_current(self) -> List[SchedulerAction]:
        """Skip the current slice and move to the next candidate."""
        with self._lock:
            if self._state in (
                SchedulerState.ACQUIRING,
                SchedulerState.DECODING,
            ):
                return self._stop_and_advance()
            return []

    def request_rescan(self) -> List[SchedulerAction]:
        """Stop the current slice and start a fresh discovery scan."""
        with self._lock:
            actions: List[SchedulerAction] = []
            if self._state in (
                SchedulerState.ACQUIRING,
                SchedulerState.DECODING,
            ):
                actions.append(
                    SchedulerAction(
                        ActionKind.STOP_DECODER,
                        slice_id=self._current_slice_id,
                    )
                )
                self._finish_current_slice()
            elif self._state == SchedulerState.SCANNING:
                actions.append(SchedulerAction(ActionKind.STOP_SCAN))
            self._scan_gen += 1
            self._new_candidate_served_this_rotation.clear()
            self._state = SchedulerState.SCANNING
            actions.append(SchedulerAction(ActionKind.START_SCAN))
            logging.info("TimeSlice - immediate rescan requested")
            return actions

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return a snapshot of scheduler state for the web interface."""
        with self._lock:
            next_candidate = self._pick_next_candidate()
            now = self._clock()
            elapsed = 0.0
            remaining = None
            if self._decoder_start_time is not None:
                elapsed = max(0.0, now - self._decoder_start_time)
                hard_remaining = max(0.0, self._hard_limit - elapsed)
                if self._state == SchedulerState.ACQUIRING:
                    remaining = min(
                        hard_remaining,
                        max(0.0, self._acquire_timeout - elapsed),
                    )
                elif (
                    self._state == SchedulerState.DECODING
                    and self._first_valid_frame_time is not None
                ):
                    remaining = min(
                        hard_remaining,
                        max(
                            0.0,
                            self._decode_time
                            - (now - self._first_valid_frame_time),
                        ),
                    )
            served_count = sum(
                1
                for rec in self._candidates.values()
                if rec.last_served_rotation == self._rotation
            )
            return {
                "enabled": True,
                "state": self._state.value,
                "scan_generation": self._scan_gen,
                "current_slice_id": self._current_slice_id or None,
                "current_frequency": self._current_freq,
                "current_sonde_type": self._current_sonde_type,
                "next_frequency": (
                    next_candidate.frequency if next_candidate else None
                ),
                "next_sonde_type": (
                    next_candidate.sonde_type if next_candidate else None
                ),
                "candidate_count": len(self._candidates),
                "served_count": served_count,
                "rotation": self._rotation,
                "elapsed_seconds": round(elapsed, 1),
                "remaining_seconds": (
                    round(remaining, 1) if remaining is not None else None
                ),
                "candidates": {
                    freq: {
                        "state": rec.state.value,
                        "sonde_type": rec.sonde_type,
                        "ever_decoded": rec.ever_produced_valid_frame,
                        "last_served_rotation": rec.last_served_rotation,
                    }
                    for freq, rec in self._candidates.items()
                },
            }

    def get_known_candidates(self) -> Dict[int, str]:
        """Return confirmed frequency-to-type mappings for scanner reuse."""
        with self._lock:
            return {
                rec.frequency: rec.sonde_type
                for rec in self._candidates.values()
                if rec.ever_produced_valid_frame
            }

    # ------------------------------------------------------------------
    # Private helpers (all called with self._lock held)
    # ------------------------------------------------------------------

    def _upsert_candidate(
        self, frequency: int, sonde_type: str, scan_gen: int
    ) -> None:
        """Insert a new candidate or refresh an existing one."""
        existing = self._candidates.get(frequency)
        if existing is None:
            self._candidates[frequency] = CandidateRecord(
                frequency=frequency,
                sonde_type=sonde_type,
                first_scan_gen=scan_gen,
                last_scan_gen=scan_gen,
                state=CandidateState.NEW,
            )
            logging.debug(
                "TimeSlice - new candidate %.3f MHz (%s)",
                frequency / 1e6,
                sonde_type,
            )
        else:
            existing.last_scan_gen = scan_gen
            existing._consecutive_misses = 0
            if existing.sonde_type != sonde_type:
                # Different type at same quantized frequency — treat as new.
                logging.debug(
                    "TimeSlice - type change at %.3f MHz: %s -> %s, resetting",
                    frequency / 1e6,
                    existing.sonde_type,
                    sonde_type,
                )
                existing.sonde_type = sonde_type
                existing.state = CandidateState.NEW
                existing.ever_produced_valid_frame = False
                existing.first_valid_frame_time = None
                existing.last_valid_frame_time = None
                existing.last_served_rotation = -1
            elif existing.state == CandidateState.STALE:
                existing.state = (
                    CandidateState.CONFIRMED
                    if existing.ever_produced_valid_frame
                    else CandidateState.NEW
                )

    def _pick_next_candidate(self) -> Optional[CandidateRecord]:
        """Return the next candidate to serve, or None if none are eligible.

        Priority:
        1. NEW candidates not yet served this rotation (one trial each).
        2. CONFIRMED or STALE candidates with the smallest last_served_rotation
           (oldest-first to prevent starvation).
        """
        eligible = [
            rec for rec in self._candidates.values()
            if rec.state not in (CandidateState.ACQUIRING, CandidateState.WAITING)
        ]
        if not eligible:
            return None

        new_candidates = [
            rec for rec in eligible
            if rec.state == CandidateState.NEW
            and rec.frequency not in self._new_candidate_served_this_rotation
        ]
        if new_candidates:
            return min(new_candidates, key=lambda r: r.first_scan_gen)

        returning = [
            rec for rec in eligible
            if rec.state in (CandidateState.CONFIRMED, CandidateState.STALE)
            and rec.last_served_rotation < self._rotation
        ]
        if returning:
            return min(returning, key=lambda r: r.last_served_rotation)

        # All confirmed candidates have been served in this rotation.
        return None

    def _start_next_slice(self) -> List[SchedulerAction]:
        """Pick the next candidate and start a decoder slice for it.

        If no candidate is eligible, returns a START_SCAN action instead.
        """
        candidate = self._pick_next_candidate()
        if candidate is None:
            # All candidates served — start a new rotation with a rescan.
            self._rotation += 1
            self._new_candidate_served_this_rotation.clear()
            logging.info(
                "TimeSlice - rotation %d complete, starting fresh scan",
                self._rotation,
            )
            self._state = SchedulerState.SCANNING
            return [SchedulerAction(ActionKind.START_SCAN)]

        # Mark candidate as being served.
        if candidate.state == CandidateState.NEW:
            self._new_candidate_served_this_rotation.add(candidate.frequency)
        candidate.state = CandidateState.ACQUIRING
        candidate.last_served_rotation = self._rotation

        slice_id = self._next_slice_id
        self._next_slice_id += 1
        self._current_slice_id = slice_id
        self._current_freq = candidate.frequency
        self._current_sonde_type = candidate.sonde_type
        self._decoder_start_time = None
        self._first_valid_frame_time = None
        self._state = SchedulerState.ACQUIRING

        logging.info(
            "TimeSlice - starting slice %d: %.3f MHz (%s)",
            slice_id,
            candidate.frequency / 1e6,
            candidate.sonde_type,
        )
        return [
            SchedulerAction(
                ActionKind.START_DECODER,
                frequency=candidate.frequency,
                sonde_type=candidate.sonde_type,
                slice_id=slice_id,
            )
        ]

    def _finish_current_slice(self) -> None:
        """Reset per-slice state after the decoder exits."""
        if self._current_freq is not None:
            rec = self._candidates.get(self._current_freq)
            if rec is not None and rec.state == CandidateState.ACQUIRING:
                # Ended without a valid frame — leave as NEW (eligible for retry).
                rec.state = (
                    CandidateState.CONFIRMED
                    if rec.ever_produced_valid_frame
                    else CandidateState.NEW
                )
        self._current_slice_id = 0
        self._current_freq = None
        self._current_sonde_type = None
        self._decoder_start_time = None
        self._first_valid_frame_time = None

    def _stop_and_advance(self) -> List[SchedulerAction]:
        """Emit a STOP_DECODER action then select the next step."""
        actions = [
            SchedulerAction(
                ActionKind.STOP_DECODER,
                slice_id=self._current_slice_id,
            )
        ]
        self._finish_current_slice()
        actions.extend(self._advance())
        return actions

    def _advance(self) -> List[SchedulerAction]:
        """Select the next scheduler action after any scan or decoder ends.

        Called from on_scan_cycle_complete, on_decoder_complete, and
        _stop_and_advance.  Assumes the lock is held.
        """
        if self._rescan_requested:
            self._rescan_requested = False
            self._state = SchedulerState.SCANNING
            return [SchedulerAction(ActionKind.START_SCAN)]
        return self._start_next_slice()


# ---------------------------------------------------------------------------
# Configuration validation helper
# ---------------------------------------------------------------------------

def validate_time_slice_config(config: dict) -> None:
    """Raise ValueError if the time-slice configuration is inconsistent.

    Call this from ``read_auto_rx_config`` after the full config dict is built.
    """
    if not config.get("time_slice_enabled", False):
        return

    if config.get("sdr_type") != "RTL_TCP":
        raise ValueError(
            "time_slice_enabled requires sdr_type = RTL_TCP"
        )
    if int(config.get("sdr_quantity", 1)) != 1:
        raise ValueError(
            "time_slice_enabled requires sdr_quantity = 1"
        )
    if config.get("always_decode"):
        raise ValueError(
            "time_slice_enabled is incompatible with a non-empty always_decode list; "
            "an always-on decoder would permanently own the single tuner"
        )

    acquire = float(config.get("time_slice_acquire_timeout", 10))
    decode = float(config.get("time_slice_decode_time", 15))
    hard = float(config.get("time_slice_hard_limit", 25))

    if not all(math.isfinite(value) for value in (acquire, decode, hard)):
        raise ValueError("time-slice timeout values must be finite")

    if acquire <= 0:
        raise ValueError("time_slice_acquire_timeout must be positive")
    if decode <= 0:
        raise ValueError("time_slice_decode_time must be positive")
    if hard < acquire + decode:
        raise ValueError(
            f"time_slice_hard_limit ({hard}) must be >= "
            f"acquire_timeout ({acquire}) + decode_time ({decode})"
        )
