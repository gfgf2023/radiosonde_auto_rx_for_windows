import subprocess

from autorx import ka9q
from autorx import platform
from autorx import scan
from autorx import sdr_wrappers


def test_rtl_power_uses_a_python_timeout_without_a_windows_numeric_prefix(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        scan.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 0),
    )

    assert scan.run_rtl_power(
        400000000,
        401000000,
        1000,
        filename=str(tmp_path / "power.csv"),
        dwell=4,
        rtl_power_path="rtl_power.exe",
    )

    assert calls[0][0][0].startswith("rtl_power.exe ")
    assert calls[0][1]["timeout"] == 14


def test_rtl_power_quotes_windows_tool_and_log_paths(monkeypatch):
    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        scan.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 0),
    )

    assert scan.run_rtl_power(
        400000000,
        401000000,
        1000,
        filename=r"C:\Program Files\auto_rx\power.csv",
        rtl_power_path=r"C:\Program Files\rtl\rtl_power.exe",
    )

    assert r'"C:\Program Files\rtl\rtl_power.exe"' in calls[0][0][0]
    assert r'"C:\Program Files\auto_rx\power.csv"' in calls[0][0][0]


def test_sync_detection_quotes_windows_decoder_path(monkeypatch):
    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(scan, "get_sdr_iq_cmd", lambda **kwargs: "source | ")
    monkeypatch.setattr(scan, "get_sdr_name", lambda *args, **kwargs: "SpyServer")
    monkeypatch.setattr(
        scan.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 1, stdout=b""),
    )

    assert scan.detect_sonde(
        401500000,
        rs_path=r"C:\Program Files\auto_rx",
        sdr_type="SpyServer",
        ss_iq_path="ignored",
    ) == (None, 0.0)

    assert r'"C:\Program Files\auto_rx\dft_detect.exe"' in calls[0][0][0]


def test_windows_detection_timeout_is_a_completed_probe_not_an_sdr_failure(
    monkeypatch,
):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(scan, "get_sdr_iq_cmd", lambda **kwargs: "source | ")
    monkeypatch.setattr(scan, "get_sdr_name", lambda *args, **kwargs: "RTL-TCP")
    monkeypatch.setattr(scan, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan.autorx_platform,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"")
        ),
    )

    assert scan.detect_sonde(401500000, sdr_type="RTL_TCP") == (None, 0.0)


def test_ka9q_setup_uses_a_python_timeout_without_a_windows_numeric_prefix(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        ka9q.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 0),
    )

    assert ka9q.ka9q_setup_channel("sonde.local", 401500000, 48000, False)

    assert calls[0][0][0].startswith("tune ")
    assert calls[0][1]["timeout"] == 5


def test_spyserver_check_uses_a_python_timeout_without_a_windows_numeric_prefix(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(sdr_wrappers.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(
        sdr_wrappers.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 0),
    )

    assert sdr_wrappers.test_sdr(
        "SpyServer", ss_iq_path="ss_iq.exe", sdr_hostname="spy.local", timeout=7
    )

    assert calls[0][0][0].startswith("ss_iq.exe ")
    assert calls[0][1]["timeout"] == 7
