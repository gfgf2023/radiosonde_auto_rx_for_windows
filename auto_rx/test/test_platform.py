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


def test_translate_command_resolves_windows_local_decoder_executable(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert (
        platform.translate_command("./rs41mod --json 2>/dev/null")
        == r".\rs41mod.exe --json 2>NUL"
    )


def test_translate_command_resolves_windows_local_decoder_pipeline(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert (
        platform.translate_command("./iq_dec --iq | ./weathex301d --json 2>/dev/null")
        == r".\iq_dec.exe --iq | .\weathex301d.exe --json 2>NUL"
    )


@pytest.mark.parametrize("metacharacter", ["&", "|", "<", ">", "(", ")", "^"])
def test_quote_command_argument_quotes_windows_cmd_metacharacters(
    monkeypatch, metacharacter
):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    argument = r"C:\tools" + metacharacter + r"qa\dft_detect"

    assert platform.quote_command_argument(argument) == '"' + argument + '"'


def test_quote_command_argument_uses_windows_quote_escaping(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert (
        platform.quote_command_argument('C:\\tools"qa\\dft_detect')
        == r'"C:\tools\"qa\dft_detect"'
    )


@pytest.mark.skipif(not platform.is_windows(), reason="requires cmd.exe")
def test_quote_command_argument_runs_cmd_script_from_metacharacter_path(tmp_path):
    script_directory = tmp_path / "tools&qa"
    script_directory.mkdir()
    script = script_directory / "probe.cmd"
    script.write_text("@echo SAFE\r\n", encoding="ascii")

    result = platform.run_command(
        platform.quote_command_argument(str(script)), capture_output=True, check=True
    )

    assert result.stdout.strip() == b"SAFE"


@pytest.mark.skipif(not platform.is_windows(), reason="requires cmd.exe")
def test_quote_command_argument_rejects_literal_percent_path_before_cmd(tmp_path):
    script_directory = tmp_path / "%PATH%"
    script_directory.mkdir()
    script = script_directory / "probe.cmd"
    script.write_text("@echo SAFE\r\n", encoding="ascii")

    with pytest.raises(ValueError, match="percent"):
        platform.run_command(platform.quote_command_argument(str(script)))


def test_run_command_rejects_windows_percent_expansion_before_shell(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setenv("AUTORX_SCAN_FREQUENCY", "401500000")
    monkeypatch.setattr(
        platform.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("command must not reach cmd.exe"),
    )

    with pytest.raises(ValueError, match="percent"):
        platform.run_command("rtl_power -f %AUTORX_SCAN_FREQUENCY%", shell=True)


def test_prepare_shell_command_rejects_windows_percent_in_list_form(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    with pytest.raises(ValueError, match="percent"):
        platform.prepare_shell_command(["rtl_power", "-f", "%AUTORX_SCAN_FREQUENCY%"])


def test_prepare_shell_command_allows_isolated_windows_percent(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.prepare_shell_command("rtl_power -c 25%") == "rtl_power -c 25%"


def test_prepare_shell_command_translates_percent_free_windows_commands(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.prepare_shell_command("./rs41mod --json") == r".\rs41mod.exe --json"
    assert platform.prepare_shell_command(["./rs41mod", "--json"]) == [
        r".\rs41mod.exe",
        "--json",
    ]


def test_platform_helpers_preserve_linux_commands(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")

    assert platform.is_windows() is False
    assert platform.null_device() == "/dev/null"
    assert platform.resolve_executable("./rs41mod") == "./rs41mod"
    assert platform.translate_command("rs41mod 2>/dev/null") == "rs41mod 2>/dev/null"
    assert platform.quote_command_argument("decoder path") == "'decoder path'"


def test_popen_kwargs_uses_a_windows_process_group(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")

    assert platform.popen_kwargs() == {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    }


def test_popen_kwargs_starts_a_new_posix_session(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")

    assert platform.popen_kwargs() == {"start_new_session": True}


def test_run_command_returns_subprocess_result_with_timeout(monkeypatch):
    class Process:
        args = "decoder 2>NUL"
        returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, input=None, timeout=None):
            assert input is None
            assert timeout == 5
            return (b"ok", b"")

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    created = {}

    def fake_popen(*args, **kwargs):
        created["args"] = args
        created["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.subprocess, "Popen", fake_popen)

    result = platform.run_command("decoder 2>/dev/null", timeout=5, capture_output=True)

    assert result.args == "decoder 2>NUL"
    assert result.stdout == b"ok"
    assert created == {
        "args": ("decoder 2>NUL",),
        "kwargs": {
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "creationflags": getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            ),
        },
    }


def test_run_command_terminates_the_process_tree_on_timeout(monkeypatch):
    class Process:
        args = "decoder"
        returncode = -9

        def __init__(self):
            self.timeouts = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, input=None, timeout=None):
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return (b"", b"")

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self):
            return self.returncode

    process = Process()
    terminated = []

    monkeypatch.setattr(platform.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(platform, "terminate_process_tree", terminated.append)

    with pytest.raises(subprocess.TimeoutExpired):
        platform.run_command("decoder", timeout=1)

    assert terminated == [process]
    assert process.timeouts == [1, None]


def test_terminate_process_tree_uses_taskkill_on_windows(monkeypatch):
    class Process:
        pid = 123

        def kill(self):
            raise AssertionError("taskkill should be sufficient")

    calls = []
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        platform.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args[0], 0),
    )

    platform.terminate_process_tree(Process())

    assert calls == [
        ((["taskkill", "/PID", "123", "/T", "/F"],), {
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        })
    ]


def test_terminate_process_tree_falls_back_when_taskkill_fails(monkeypatch):
    class Process:
        pid = 123

        def __init__(self):
            self.killed = False
            self.waited = False

        def kill(self):
            self.killed = True

        def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        platform.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    platform.terminate_process_tree(process)

    assert process.killed is True
    assert process.waited is True


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
