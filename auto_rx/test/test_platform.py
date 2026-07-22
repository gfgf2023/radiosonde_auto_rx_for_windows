from autorx import platform


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
