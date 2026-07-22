import subprocess

import pytest

from autorx import platform
from autorx import utils


def test_is_windows_detects_win32(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.is_windows() is True


def test_null_device_is_nul_on_windows(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.null_device() == "NUL"


def test_resolve_executable_adds_exe_suffix_on_windows(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.resolve_executable("./rs41mod") == "./rs41mod.exe"


def test_translate_command_uses_nul_on_windows(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.translate_command("rs41mod 2>/dev/null") == "rs41mod 2>NUL"


def test_platform_helpers_preserve_linux_commands(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")

    assert platform.is_windows() is False
    assert platform.null_device() == "/dev/null"
    assert platform.resolve_executable("./rs41mod") == "./rs41mod"
    assert platform.translate_command("rs41mod 2>/dev/null") == "rs41mod 2>/dev/null"


def test_popen_kwargs_uses_a_windows_process_group(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.popen_kwargs() == {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    }


def test_run_command_returns_subprocess_result_with_timeout(monkeypatch):
    expected = subprocess.CompletedProcess("decoder 2>NUL", 0, stdout=b"ok")

    def fake_run(*args, **kwargs):
        assert args == ("decoder 2>NUL",)
        assert kwargs == {"shell": True, "timeout": 5, "capture_output": True}
        return expected

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.subprocess, "run", fake_run)

    assert platform.run_command("decoder 2>/dev/null", timeout=5, capture_output=True) is expected


def test_run_command_propagates_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(platform.subprocess, "run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        platform.run_command("decoder", timeout=1)


def test_terminate_process_tree_uses_taskkill_on_windows(monkeypatch):
    class Process:
        pid = 123

        def kill(self):
            raise AssertionError("taskkill should be sufficient")

    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    platform.terminate_process_tree(Process())

    assert calls == [
        ((["taskkill", "/PID", "123", "/T", "/F"],), {
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        })
    ]


def test_startup_helper_resolves_windows_decoder_executables_without_timeout_command(
    monkeypatch,
):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(utils, "REQUIRED_RS_UTILS", ["rs41mod"])
    monkeypatch.setattr(utils.os.path, "isfile", lambda path: path == "rs41mod.exe")
    monkeypatch.setattr(utils, "_timeout_cmd", None)

    assert utils.timeout_cmd() == ""
    assert utils.check_rs_utils({}) is True


def test_reset_usb_is_unavailable_on_windows_without_opening_a_device(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "win32")
    monkeypatch.setattr(utils, "open", lambda *args: pytest.fail("unexpected USB open"), raising=False)

    assert utils.reset_usb(1, 2) is False
