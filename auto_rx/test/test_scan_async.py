import asyncio

import pytest

import autorx
from autorx import platform
from autorx import scan_async
from autorx import sdr_wrappers


def test_async_ka9q_command_uses_windows_translation(monkeypatch):
    captured = {}

    class Process:
        returncode = 1

        async def communicate(self):
            return (b"", b"")

        async def wait(self):
            return self.returncode

        def kill(self):
            raise AssertionError("completed process should not be killed")

    async def fake_create_subprocess_shell(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        sdr_wrappers, "get_sdr_iq_cmd", lambda **kwargs: "pcmrecord --raw sonde | "
    )
    monkeypatch.setattr(sdr_wrappers, "get_sdr_name", lambda *args, **kwargs: "KA9Q sonde")
    monkeypatch.setattr(sdr_wrappers, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan_async.asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )

    asyncio.run(
        scan_async.detect_sonde_async(
            frequency=401500000, rs_path="./", sdr_type="KA9Q", dwell_time=1
        )
    )

    assert captured["command"].endswith("dft_detect.exe -t 1 --iq --bw 15 --dc - 48000 16 2>NUL")
    assert captured["kwargs"]["creationflags"] == getattr(
        __import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0x00000200
    )


def test_async_ka9q_command_preserves_windows_cmd_quoting(monkeypatch):
    captured = {}

    class Process:
        returncode = 1

        async def communicate(self):
            return (b"", b"")

        async def wait(self):
            return self.returncode

        def kill(self):
            raise AssertionError("completed process should not be killed")

    async def fake_create_subprocess_shell(command, **kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        sdr_wrappers, "get_sdr_iq_cmd", lambda **kwargs: "pcmrecord --raw sonde | "
    )
    monkeypatch.setattr(sdr_wrappers, "get_sdr_name", lambda *args, **kwargs: "KA9Q sonde")
    monkeypatch.setattr(sdr_wrappers, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan_async.asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )

    asyncio.run(
        scan_async.detect_sonde_async(
            frequency=401500000,
            rs_path=r"C:\tools&qa",
            sdr_type="KA9Q",
            dwell_time=1,
        )
    )

    assert r'"C:\tools&qa\dft_detect.exe"' in captured["command"]


def test_async_ka9q_command_rejects_windows_percent_expansion(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        sdr_wrappers,
        "get_sdr_iq_cmd",
        lambda **kwargs: "pcmrecord %PATH% | ",
    )
    monkeypatch.setattr(sdr_wrappers, "get_sdr_name", lambda *args, **kwargs: "KA9Q sonde")
    monkeypatch.setattr(sdr_wrappers, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan_async.asyncio,
        "create_subprocess_shell",
        lambda *args, **kwargs: pytest.fail("command must not reach the shell"),
    )

    with pytest.raises(ValueError, match="percent"):
        asyncio.run(
            scan_async.detect_sonde_async(
                frequency=401500000, rs_path="./", sdr_type="KA9Q", dwell_time=1
            )
        )


def test_async_debug_capture_suppresses_windows_tee(monkeypatch):
    captured = {}

    class Process:
        returncode = 1

        async def communicate(self):
            return (b"", b"")

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_shell(command, **kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(autorx, "logging_path", r"C:\debug")
    monkeypatch.setattr(
        sdr_wrappers, "get_sdr_iq_cmd", lambda **kwargs: "pcmrecord --raw sonde | "
    )
    monkeypatch.setattr(sdr_wrappers, "get_sdr_name", lambda *args, **kwargs: "KA9Q sonde")
    monkeypatch.setattr(sdr_wrappers, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan_async.asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )

    asyncio.run(
        scan_async.detect_sonde_async(
            frequency=401500000,
            rs_path="./",
            sdr_type="KA9Q",
            dwell_time=1,
            save_detection_audio=True,
        )
    )

    assert "tee " not in captured["command"]


def test_async_spyserver_quotes_windows_ss_iq_path(monkeypatch):
    captured = {}

    class Process:
        returncode = 1

        async def communicate(self):
            return (b"", b"")

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_shell(command, **kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(sdr_wrappers, "get_sdr_name", lambda *args, **kwargs: "SpyServer")
    monkeypatch.setattr(sdr_wrappers, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan_async.asyncio, "create_subprocess_shell", fake_create_subprocess_shell
    )

    asyncio.run(
        scan_async.detect_sonde_async(
            frequency=401500000,
            rs_path="./",
            sdr_type="SpyServer",
            ss_iq_path=r"C:\Program Files\spyserver\ss_iq.exe",
        )
    )

    assert captured["command"].startswith(r'"C:\Program Files\spyserver\ss_iq.exe" ')
