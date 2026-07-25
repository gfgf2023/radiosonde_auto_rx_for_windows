import importlib.util
import json
from pathlib import Path
from queue import Empty, Queue

import autorx
from autorx import config, decode, scan, web
from autorx.time_slice import ActionKind, SchedulerAction, TimeSliceScheduler


def _make_scanner(**overrides):
    scanner = scan.SondeScanner.__new__(scan.SondeScanner)
    scanner.quantization = overrides.get("quantization", 10_000)
    scanner.known_candidates = overrides.get("known_candidates", {})
    scanner.cycle_completion_callback = overrides.get("cycle_callback")
    scanner.scan_generation = overrides.get("scan_generation", 0)
    scanner.sonde_scanner_running = True
    scanner.log_error = lambda *args: None
    return scanner


def _load_task_manager():
    path = Path(__file__).resolve().parents[1] / "auto_rx.py"
    spec = importlib.util.spec_from_file_location("autorx_task_manager", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scanner_reuses_nearby_known_candidate_frequency_and_type():
    scanner = _make_scanner(
        known_candidates={400_438_000: "CF6GTH", 401_500_000: "RS41"}
    )

    assert scanner.known_candidate_for_peak(400_440_000) == (
        400_438_000,
        "CF6GTH",
    )
    assert scanner.known_candidate_for_peak(400_443_000) == (
        400_438_000,
        "CF6GTH",
    )
    assert scanner.known_candidate_for_peak(402_000_000) is None


def test_scanner_cycle_completion_reports_seen_frequencies_and_generation():
    calls = []
    scanner = _make_scanner(
        cycle_callback=lambda frequencies, generation: calls.append(
            (frequencies, generation)
        ),
        scan_generation=7,
    )

    scanner.send_cycle_completion(
        [[400_438_000.0, "CF6GTH"], [401_500_000, "RS41"]]
    )

    assert calls == [([400_438_000, 401_500_000], 7)]


def test_decoder_reports_valid_filtered_frame_to_scheduler_callback(monkeypatch):
    frames = []
    decoder_instance = decode.SondeDecoder.__new__(decode.SondeDecoder)
    decoder_instance.raw_file = None
    decoder_instance.udp_mode = False
    decoder_instance.sonde_type = "RS41"
    decoder_instance.close_on_encrypted = True
    decoder_instance.sonde_freq = 401_500_000
    decoder_instance.rtl_device_idx = "RTL_TCP-01"
    decoder_instance.demod_stats = None
    decoder_instance.telem_filter = None
    decoder_instance.enable_realtime_filter = False
    decoder_instance.last_positions = {}
    decoder_instance.exporters = None
    decoder_instance.valid_frame_callback = frames.append
    decoder_instance.slice_id = 12
    decoder_instance.log_error = lambda *args: None
    decoder_instance.log_debug = lambda *args: None
    decoder_instance.log_critical = lambda *args: None
    monkeypatch.setattr(decode, "generate_aprs_id", lambda telemetry: "TEST")

    telemetry = {
        "frame": 1,
        "id": "TEST1234",
        "datetime": "2026-07-26T00:00:00Z",
        "lat": 1.0,
        "lon": 2.0,
        "alt": 3.0,
        "version": autorx.__version__,
    }

    assert decoder_instance.handle_decoder_line(
        json.dumps(telemetry).encode("ascii")
    ) == "OK"
    assert frames == [12]


def test_task_manager_stops_scanner_before_starting_slice_decoder(monkeypatch):
    task_manager = _load_task_manager()
    calls = []
    monkeypatch.setattr(autorx, "time_slice_actions", Queue())
    monkeypatch.setattr(autorx, "task_list", {"SCAN": {}})
    monkeypatch.setattr(
        task_manager,
        "stop_scanner",
        lambda: (calls.append("stop_scan"), autorx.task_list.pop("SCAN")),
    )
    monkeypatch.setattr(
        task_manager,
        "start_decoder",
        lambda frequency, sonde_type, slice_id=None: calls.append(
            ("start_decoder", frequency, sonde_type, slice_id)
        ) or True,
    )
    autorx.time_slice_actions.put(
        SchedulerAction(
            ActionKind.START_DECODER,
            frequency=400_438_000,
            sonde_type="CF6GTH",
            slice_id=3,
        )
    )

    task_manager.execute_time_slice_actions()

    assert calls == [
        "stop_scan",
        ("start_decoder", 400_438_000, "CF6GTH", 3),
    ]


def test_task_manager_restarts_scanner_for_new_scan_generation(monkeypatch):
    task_manager = _load_task_manager()
    calls = []
    monkeypatch.setattr(autorx, "time_slice_actions", Queue())
    monkeypatch.setattr(autorx, "task_list", {"SCAN": {}})
    monkeypatch.setattr(autorx, "scan_inhibit", False)

    def stop_scan():
        calls.append("stop_scan")
        autorx.task_list.pop("SCAN")

    monkeypatch.setattr(task_manager, "stop_scanner", stop_scan)
    monkeypatch.setattr(task_manager, "start_scanner", lambda: calls.append("start_scan"))
    autorx.time_slice_actions.put(SchedulerAction(ActionKind.START_SCAN))

    task_manager.execute_time_slice_actions()

    assert calls == ["stop_scan", "start_scan"]


def test_task_manager_ignores_stale_decoder_action_after_rescan(monkeypatch):
    task_manager = _load_task_manager()
    scheduler = TimeSliceScheduler()
    scheduler.on_scan_detection(400_438_000, "CF6GTH", 0)
    stale_actions = scheduler.on_scan_cycle_complete([400_438_000], 0)
    scheduler.request_rescan()
    monkeypatch.setattr(autorx, "time_slice_scheduler", scheduler)
    monkeypatch.setattr(autorx, "time_slice_actions", Queue())
    monkeypatch.setattr(autorx, "task_list", {})
    monkeypatch.setattr(autorx, "scan_inhibit", False)
    monkeypatch.setattr(
        task_manager,
        "start_decoder",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stale decoder must not start")
        ),
    )
    autorx.time_slice_actions.put(tuple(stale_actions))

    task_manager.execute_time_slice_actions()

    assert autorx.time_slice_actions.empty()


def test_task_manager_defers_next_slice_while_scanner_is_disabled(monkeypatch):
    task_manager = _load_task_manager()
    scheduler = TimeSliceScheduler()
    scheduler.on_scan_detection(400_438_000, "CF6GTH", 0)
    actions = scheduler.on_scan_cycle_complete([400_438_000], 0)
    calls = []
    monkeypatch.setattr(autorx, "time_slice_scheduler", scheduler)
    monkeypatch.setattr(autorx, "time_slice_actions", Queue())
    monkeypatch.setattr(autorx, "task_list", {})
    monkeypatch.setattr(autorx, "scan_inhibit", True)
    monkeypatch.setattr(
        task_manager,
        "start_decoder",
        lambda *args, **kwargs: calls.append("start") or True,
    )
    autorx.time_slice_actions.put(tuple(actions))

    task_manager.execute_time_slice_actions()
    assert calls == []
    assert not autorx.time_slice_actions.empty()

    autorx.scan_inhibit = False
    task_manager.execute_time_slice_actions()
    assert calls == ["start"]


def test_time_slice_web_status_and_authenticated_controls(monkeypatch):
    scheduler = TimeSliceScheduler()
    actions = scheduler.add_candidate(400_438_000, "CF6GTH")
    assert actions == []
    scheduler.on_scan_cycle_complete([400_438_000], 0)

    action_queue = Queue()
    monkeypatch.setattr(autorx, "time_slice_scheduler", scheduler)
    monkeypatch.setattr(autorx, "time_slice_actions", action_queue)
    monkeypatch.setattr(config, "global_config", {"web_control": True})
    monkeypatch.setattr(config, "web_password", "secret")
    client = web.app.test_client()

    status = client.get("/time_slice_status")
    assert status.status_code == 200
    assert status.get_json(force=True)["enabled"] is True

    assert client.post("/time_slice_skip", data={"password": "bad"}).status_code == 403
    assert client.post(
        "/time_slice_skip", data={"password": "secret"}
    ).status_code == 200
    assert action_queue.get_nowait() == {"command": "skip"}


def test_time_slice_web_rejects_unknown_decoder_type(monkeypatch):
    monkeypatch.setattr(autorx, "time_slice_scheduler", TimeSliceScheduler())
    monkeypatch.setattr(autorx, "time_slice_actions", Queue())
    monkeypatch.setattr(config, "global_config", {"web_control": True})
    monkeypatch.setattr(config, "web_password", "secret")

    response = web.app.test_client().post(
        "/start_decoder",
        data={"password": "secret", "freq": "400438000", "type": "TYPO"},
    )

    assert response.status_code == 400
    assert autorx.time_slice_scheduler.get_status()["candidate_count"] == 0


def test_time_slice_status_is_disabled_without_scheduler(monkeypatch):
    monkeypatch.setattr(autorx, "time_slice_scheduler", None)

    response = web.app.test_client().get("/time_slice_status")

    assert response.get_json(force=True) == {
        "enabled": False,
        "state": "disabled",
    }


def test_time_slice_web_rescan_queues_scan_replacement(monkeypatch):
    scheduler = TimeSliceScheduler()
    action_queue = Queue()
    monkeypatch.setattr(autorx, "time_slice_scheduler", scheduler)
    monkeypatch.setattr(autorx, "time_slice_actions", action_queue)
    monkeypatch.setattr(config, "global_config", {"web_control": True})
    monkeypatch.setattr(config, "web_password", "secret")

    response = web.app.test_client().post(
        "/time_slice_rescan",
        data={"password": "secret"},
    )

    assert response.status_code == 200
    assert action_queue.get_nowait() == {"command": "rescan"}


def test_manual_candidate_is_prioritized_for_next_slice():
    scheduler = TimeSliceScheduler()
    scheduler.on_scan_detection(401_000_000, "RS41", 0)
    scheduler.on_scan_detection(402_000_000, "DFM", 0)
    scheduler.add_candidate(400_438_000, "CF6GTH")

    actions = scheduler.on_scan_cycle_complete(
        [401_000_000, 402_000_000, 400_438_000],
        0,
    )
    start = next(action for action in actions if action.kind == ActionKind.START_DECODER)

    assert start.frequency == 400_438_000


def test_only_validated_candidates_are_reused_by_scanner():
    scheduler = TimeSliceScheduler()
    scheduler.add_candidate(400_438_000, "CF6GTH")
    assert scheduler.get_known_candidates() == {}

    start = scheduler.on_scan_cycle_complete([400_438_000], 0)[0]
    scheduler.on_decoder_started(start.slice_id)
    scheduler.on_valid_frame(start.slice_id)

    assert scheduler.get_known_candidates() == {400_438_000: "CF6GTH"}


def test_rescan_while_scanning_replaces_scan_generation():
    scheduler = TimeSliceScheduler()

    actions = scheduler.request_rescan()

    assert [action.kind for action in actions] == [
        ActionKind.STOP_SCAN,
        ActionKind.START_SCAN,
    ]
    assert scheduler.get_status()["scan_generation"] == 1
    assert scheduler.on_scan_cycle_complete([], 0) == []


def test_acquisition_budget_starts_after_decoder_owns_tuner():
    clock = type(
        "Clock",
        (),
        {
            "now": 0.0,
            "__call__": lambda self: self.now,
        },
    )()
    scheduler = TimeSliceScheduler(clock=clock)
    scheduler.on_scan_detection(401_500_000, "RS41", 0)
    start = scheduler.on_scan_cycle_complete([401_500_000], 0)[0]
    clock.now = 8.0
    scheduler.on_decoder_started(start.slice_id)

    clock.now = 17.9
    assert scheduler.tick() == []
    clock.now = 18.0
    assert scheduler.tick()[0].kind == ActionKind.STOP_DECODER
