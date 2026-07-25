"""Pure-scheduler unit tests for autorx.time_slice.

All tests use a fake monotonic clock so no real time passes.
"""
import pytest
from autorx.time_slice import (
    ActionKind,
    CandidateState,
    SchedulerAction,
    SchedulerState,
    TimeSliceScheduler,
    validate_time_slice_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeClock:
    """A manually-advanceable monotonic clock."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_scheduler(**kwargs) -> tuple:
    """Return (scheduler, clock) with sensible defaults."""
    clock = FakeClock()
    s = TimeSliceScheduler(
        acquire_timeout=kwargs.pop("acquire_timeout", 10.0),
        decode_time=kwargs.pop("decode_time", 15.0),
        hard_limit=kwargs.pop("hard_limit", 25.0),
        clock=clock,
        **kwargs,
    )
    return s, clock


def action_kinds(actions):
    return [a.kind for a in actions]


def start_scan_and_detect(scheduler, freqs, sonde_type="RS41", scan_gen=0):
    """Feed detections and a cycle-complete event; return cycle-complete actions."""
    for freq in freqs:
        scheduler.on_scan_detection(freq, sonde_type, scan_gen)
    actions = scheduler.on_scan_cycle_complete(freqs, scan_gen)
    for action in actions:
        if action.kind == ActionKind.START_DECODER:
            scheduler.on_decoder_started(action.slice_id)
    return actions


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_scheduler_starts_in_scanning_state():
    s, _ = make_scheduler()
    assert s.get_status()["state"] == "scanning"


def test_invalid_config_raises():
    with pytest.raises(ValueError):
        TimeSliceScheduler(acquire_timeout=-1)
    with pytest.raises(ValueError):
        TimeSliceScheduler(decode_time=0)
    with pytest.raises(ValueError):
        TimeSliceScheduler(acquire_timeout=10, decode_time=15, hard_limit=24)


# ---------------------------------------------------------------------------
# Single candidate: happy path
# ---------------------------------------------------------------------------

def test_single_candidate_starts_decoder_after_scan():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_500_000])

    assert ActionKind.START_DECODER in action_kinds(actions)
    start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
    assert start.frequency == 401_500_000
    assert start.sonde_type == "RS41"
    assert start.slice_id == 1


def test_single_candidate_valid_frame_promotes_to_confirmed():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id

    s.on_valid_frame(slice_id)

    status = s.get_status()
    assert status["state"] == "decoding"
    assert status["candidates"][401_500_000]["ever_decoded"] is True


def test_single_candidate_decoder_complete_triggers_rescan():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id
    s.on_valid_frame(slice_id)

    next_actions = s.on_decoder_complete(slice_id)

    assert ActionKind.START_SCAN in action_kinds(next_actions)


# ---------------------------------------------------------------------------
# Acquisition timeout
# ---------------------------------------------------------------------------

def test_acquisition_timeout_stops_decoder_and_rescans():
    s, clock = make_scheduler(acquire_timeout=10.0)
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id

    clock.advance(10.0)
    timeout_actions = s.tick()

    assert ActionKind.STOP_DECODER in action_kinds(timeout_actions)
    assert ActionKind.START_SCAN in action_kinds(timeout_actions)


def test_no_timeout_before_acquire_timeout():
    s, clock = make_scheduler(acquire_timeout=10.0)
    actions = start_scan_and_detect(s, [401_500_000])

    clock.advance(9.9)
    assert s.tick() == []


# ---------------------------------------------------------------------------
# Useful decode budget (15 s after first frame)
# ---------------------------------------------------------------------------

def test_decode_budget_stops_decoder_after_valid_frame():
    s, clock = make_scheduler(decode_time=15.0, hard_limit=30.0)
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id

    clock.advance(3.0)
    s.on_valid_frame(slice_id)
    clock.advance(15.0)
    timeout_actions = s.tick()

    assert ActionKind.STOP_DECODER in action_kinds(timeout_actions)


def test_decode_budget_not_triggered_before_15s():
    s, clock = make_scheduler(decode_time=15.0, hard_limit=30.0)
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id

    clock.advance(3.0)
    s.on_valid_frame(slice_id)
    clock.advance(14.9)
    assert s.tick() == []


# ---------------------------------------------------------------------------
# Hard limit (25 s from decoder start)
# ---------------------------------------------------------------------------

def test_hard_limit_stops_decoder():
    s, clock = make_scheduler(acquire_timeout=10, decode_time=15, hard_limit=25)
    actions = start_scan_and_detect(s, [401_500_000])
    slice_id = actions[0].slice_id
    clock.advance(5.0)
    s.on_valid_frame(slice_id)

    clock.advance(20.0)  # total 25 s from start
    hard_actions = s.tick()

    assert ActionKind.STOP_DECODER in action_kinds(hard_actions)


# ---------------------------------------------------------------------------
# Four-candidate fair rotation
# ---------------------------------------------------------------------------

def _run_full_rotation(freqs, sonde_type="RS41"):
    """Run a complete rotation for the given frequencies; return slice order."""
    s, clock = make_scheduler(acquire_timeout=10, decode_time=15, hard_limit=25)
    actions = start_scan_and_detect(s, freqs, sonde_type)

    served = []
    while True:
        start = next((a for a in actions if a.kind == ActionKind.START_DECODER), None)
        if start is None:
            break
        served.append(start.frequency)
        s.on_valid_frame(start.slice_id)
        clock.advance(16.0)
        actions = s.on_decoder_complete(start.slice_id)
        if ActionKind.START_SCAN in action_kinds(actions):
            break
    return served


def test_four_candidate_rotation_serves_all():
    freqs = [401_000_000, 401_500_000, 402_000_000, 402_500_000]
    served = _run_full_rotation(freqs)
    assert set(served) == set(freqs)
    assert len(served) == 4


def test_eight_candidate_rotation_serves_all():
    freqs = [400_500_000 + i * 400_000 for i in range(8)]
    served = _run_full_rotation(freqs)
    assert set(served) == set(freqs)
    assert len(served) == 8


# ---------------------------------------------------------------------------
# New-candidate priority without starvation
# ---------------------------------------------------------------------------

def test_new_candidate_is_served_before_confirmed():
    """A NEW candidate is given priority over CONFIRMED ones in the same rotation.

    Scenario: rotation 0 ends (confirmed candidates exhausted → rescan).  The
    fresh scan re-discovers both confirmed candidates PLUS a brand-new one.
    The scheduler must serve the NEW candidate first.
    """
    s, clock = make_scheduler()

    def drain_slice(actions):
        start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
        s.on_valid_frame(start.slice_id)
        clock.advance(16)
        return s.on_decoder_complete(start.slice_id)

    # Rotation 0: two confirmed candidates, no NEW candidates pending
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000])
    actions = drain_slice(actions)   # serve first confirmed
    actions = drain_slice(actions)   # serve second confirmed
    # Both confirmed served → rotation 0 complete → rescan
    rescan = next((a for a in actions if a.kind == ActionKind.START_SCAN), None)
    assert rescan is not None, "expected START_SCAN after all confirmed served"
    assert s._rotation == 1

    # Rotation 1: rescan finds the two confirmed candidates + one NEW
    new_scan_gen = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", new_scan_gen)
    s.on_scan_detection(401_500_000, "RS41", new_scan_gen)
    s.on_scan_detection(402_000_000, "DFM", new_scan_gen)
    actions = s.on_scan_cycle_complete(
        [401_000_000, 401_500_000, 402_000_000], new_scan_gen
    )
    # The NEW 402_000_000 candidate must be served first in rotation 1
    start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
    assert start.frequency == 402_000_000


# ---------------------------------------------------------------------------
# Missed scans and stale/removal logic
# ---------------------------------------------------------------------------

def test_one_missed_scan_marks_candidate_stale():
    """A candidate absent from one complete PSD scan is marked STALE.

    Setup: Start with three candidates.  Serve all three to complete rotation 0.
    Then in rotation 1's scan, only two reappear → the absent one is marked STALE.
    """
    s, clock = make_scheduler()

    def drain_slice(actions):
        start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
        s.on_valid_frame(start.slice_id)
        clock.advance(16)
        return s.on_decoder_complete(start.slice_id)

    # Rotation 0: three candidates
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000, 402_000_000])
    actions = drain_slice(actions)  # serve first
    actions = drain_slice(actions)  # serve second
    actions = drain_slice(actions)  # serve third
    # All served → rotation 0 complete → rescan
    assert ActionKind.START_SCAN in action_kinds(actions)
    assert s._rotation == 1

    # Rotation 1 scan: only 401_000_000 and 401_500_000 appear (402_000_000 absent)
    gen = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", gen)
    s.on_scan_detection(401_500_000, "RS41", gen)
    actions = s.on_scan_cycle_complete([401_000_000, 401_500_000], gen)

    # 402_000_000 was absent → should be STALE
    assert s._candidates[402_000_000].state == CandidateState.STALE


def test_two_missed_scans_remove_candidate():
    """A candidate absent from two consecutive PSD scans is removed.

    Same setup as the one-miss test, but with a second rotation that also
    doesn't see the absent candidate.
    """
    s, clock = make_scheduler()

    def drain_slice(actions):
        start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
        s.on_valid_frame(start.slice_id)
        clock.advance(16)
        return s.on_decoder_complete(start.slice_id)

    # Rotation 0: three candidates
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000, 402_000_000])
    for _ in range(3):
        actions = drain_slice(actions)
    assert s._rotation == 1

    # Rotation 1 scan: 402_000_000 absent (miss 1)
    gen1 = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", gen1)
    s.on_scan_detection(401_500_000, "RS41", gen1)
    actions = s.on_scan_cycle_complete([401_000_000, 401_500_000], gen1)
    assert s._candidates[402_000_000].state == CandidateState.STALE

    # Serve all eligible candidates (including STALE 402_000_000) to complete rotation 1
    for _ in range(3):  # two CONFIRMED + one STALE
        actions = drain_slice(actions)
    assert s._rotation == 2

    # Rotation 2 scan: 402_000_000 absent again (miss 2)
    gen2 = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", gen2)
    s.on_scan_detection(401_500_000, "RS41", gen2)
    actions = s.on_scan_cycle_complete([401_000_000, 401_500_000], gen2)

    # Two consecutive misses → removed
    assert 402_000_000 not in s._candidates


def test_reappearance_after_one_miss_recovers_candidate():
    """A STALE candidate that reappears in the next scan is promoted back."""
    s, clock = make_scheduler()

    def drain_slice(actions):
        start = next(a for a in actions if a.kind == ActionKind.START_DECODER)
        s.on_valid_frame(start.slice_id)
        clock.advance(16)
        return s.on_decoder_complete(start.slice_id)

    # Rotation 0: three candidates
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000, 402_000_000])
    for _ in range(3):
        actions = drain_slice(actions)
    assert s._rotation == 1

    # Rotation 1 scan: 402_000_000 absent (miss 1 → STALE)
    gen1 = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", gen1)
    s.on_scan_detection(401_500_000, "RS41", gen1)
    actions = s.on_scan_cycle_complete([401_000_000, 401_500_000], gen1)
    assert s._candidates[402_000_000].state == CandidateState.STALE

    # Serve all eligible candidates (including STALE) to complete rotation 1
    for _ in range(3):  # two CONFIRMED + one STALE
        actions = drain_slice(actions)
    assert s._rotation == 2

    # Rotation 2 scan: 402_000_000 reappears
    gen2 = s._scan_gen
    s.on_scan_detection(401_000_000, "RS41", gen2)
    s.on_scan_detection(401_500_000, "RS41", gen2)
    s.on_scan_detection(402_000_000, "RS41", gen2)
    actions = s.on_scan_cycle_complete([401_000_000, 401_500_000, 402_000_000], gen2)

    # 402_000_000 recovered → should be CONFIRMED (it was confirmed in rotation 0)
    assert s._candidates[402_000_000].state in (
        CandidateState.CONFIRMED, CandidateState.ACQUIRING
    )


# ---------------------------------------------------------------------------
# Undecodable candidates: retry without blocking
# ---------------------------------------------------------------------------

def test_undecodable_candidate_stays_eligible_after_no_frame():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000])
    slice_id = actions[0].slice_id
    # No valid frame — acquisition timeout
    clock.advance(10.0)
    s.tick()
    # Candidate must still exist and not be blocked
    assert 401_000_000 in s._candidates
    rec = s._candidates[401_000_000]
    assert rec.state in (CandidateState.NEW, CandidateState.CONFIRMED,
                         CandidateState.STALE)


# ---------------------------------------------------------------------------
# Stale callback and duplicate completion rejection
# ---------------------------------------------------------------------------

def test_stale_decoder_complete_is_ignored():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000])
    slice_id = actions[0].slice_id
    s.on_valid_frame(slice_id)
    clock.advance(16)
    s.on_decoder_complete(slice_id)  # normal completion

    # Duplicate or late completion must not change state
    state_before = s.get_status()["state"]
    result = s.on_decoder_complete(slice_id)
    assert result == []
    assert s.get_status()["state"] == state_before


def test_stale_valid_frame_is_ignored():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000])
    old_slice_id = actions[0].slice_id
    # Complete first slice normally
    s.on_valid_frame(old_slice_id)
    clock.advance(16)
    next_actions = s.on_decoder_complete(old_slice_id)
    new_slice_id = next(
        a.slice_id for a in next_actions if a.kind == ActionKind.START_DECODER
    )
    # Late frame for the OLD slice must be ignored
    s.on_valid_frame(old_slice_id)
    assert s.get_status()["state"] != "scanning"  # still decoding new slice


# ---------------------------------------------------------------------------
# Manual skip
# ---------------------------------------------------------------------------

def test_skip_current_stops_decoder_and_advances():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000, 401_500_000])
    slice_id = actions[0].slice_id

    skip_actions = s.skip_current()

    assert ActionKind.STOP_DECODER in action_kinds(skip_actions)
    # Should advance to next candidate or rescan
    assert any(
        a.kind in (ActionKind.START_DECODER, ActionKind.START_SCAN)
        for a in skip_actions
    )


def test_skip_during_scanning_is_noop():
    s, _ = make_scheduler()
    assert s.skip_current() == []


# ---------------------------------------------------------------------------
# Immediate rescan
# ---------------------------------------------------------------------------

def test_request_rescan_stops_decoder_and_starts_scan():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000])
    slice_id = actions[0].slice_id

    rescan_actions = s.request_rescan()

    assert ActionKind.STOP_DECODER in action_kinds(rescan_actions)
    assert ActionKind.START_SCAN in action_kinds(rescan_actions)
    assert s.get_status()["state"] == "scanning"


def test_request_rescan_during_scanning_starts_scan():
    s, _ = make_scheduler()
    rescan_actions = s.request_rescan()
    assert ActionKind.START_SCAN in action_kinds(rescan_actions)


# ---------------------------------------------------------------------------
# Rescanning after every complete rotation
# ---------------------------------------------------------------------------

def test_rotation_complete_triggers_rescan():
    s, clock = make_scheduler()
    actions = start_scan_and_detect(s, [401_000_000])
    slice_id = actions[0].slice_id
    s.on_valid_frame(slice_id)
    clock.advance(16)
    next_actions = s.on_decoder_complete(slice_id)

    assert ActionKind.START_SCAN in action_kinds(next_actions)
    assert s.get_status()["rotation"] == 1


# ---------------------------------------------------------------------------
# Type change at same frequency treated as new candidate
# ---------------------------------------------------------------------------

def test_type_change_at_same_frequency_resets_candidate():
    s, clock = make_scheduler()
    s.on_scan_detection(401_000_000, "RS41", 0)
    s.on_scan_cycle_complete([401_000_000], 0)
    # Mark as confirmed
    rec = s._candidates[401_000_000]
    rec.ever_produced_valid_frame = True
    rec.state = CandidateState.CONFIRMED
    gen = s._scan_gen
    # New scan detects different type at same frequency
    s.on_scan_detection(401_000_000, "DFM", gen)
    assert s._candidates[401_000_000].sonde_type == "DFM"
    assert s._candidates[401_000_000].state == CandidateState.NEW
    assert s._candidates[401_000_000].ever_produced_valid_frame is False


# ---------------------------------------------------------------------------
# validate_time_slice_config
# ---------------------------------------------------------------------------

def test_validate_accepts_correct_config():
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTL_TCP",
        "sdr_quantity": 1,
        "always_decode": [],
        "time_slice_acquire_timeout": 10,
        "time_slice_decode_time": 15,
        "time_slice_hard_limit": 25,
    }
    validate_time_slice_config(config)  # must not raise


def test_validate_rejects_wrong_sdr_type():
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTLSDR",
        "sdr_quantity": 1,
        "always_decode": [],
    }
    with pytest.raises(ValueError, match="sdr_type"):
        validate_time_slice_config(config)


def test_validate_rejects_always_decode():
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTL_TCP",
        "sdr_quantity": 1,
        "always_decode": [401_000_000],
    }
    with pytest.raises(ValueError, match="always_decode"):
        validate_time_slice_config(config)


def test_validate_rejects_multiple_rtl_tcp_tuners():
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTL_TCP",
        "sdr_quantity": 2,
        "always_decode": [],
    }
    with pytest.raises(ValueError, match="sdr_quantity"):
        validate_time_slice_config(config)


def test_validate_rejects_hard_limit_too_small():
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTL_TCP",
        "sdr_quantity": 1,
        "always_decode": [],
        "time_slice_acquire_timeout": 10,
        "time_slice_decode_time": 15,
        "time_slice_hard_limit": 20,
    }
    with pytest.raises(ValueError, match="hard_limit"):
        validate_time_slice_config(config)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf")])
def test_validate_rejects_non_finite_timeouts(invalid_value):
    config = {
        "time_slice_enabled": True,
        "sdr_type": "RTL_TCP",
        "sdr_quantity": 1,
        "always_decode": [],
        "time_slice_acquire_timeout": invalid_value,
        "time_slice_decode_time": 15,
        "time_slice_hard_limit": 25,
    }
    with pytest.raises(ValueError, match="finite"):
        validate_time_slice_config(config)


def test_validate_disabled_config_skips_all_checks():
    # Nonsensical config that would fail if enabled
    config = {
        "time_slice_enabled": False,
        "sdr_type": "RTLSDR",
        "sdr_quantity": 5,
        "always_decode": [401_000_000],
    }
    validate_time_slice_config(config)  # must not raise
