import pytest

from autorx import decode
from autorx import platform


class _Reader:
    def __init__(self, *args, **kwargs):
        self.stopped = False
        self.joined = False

    def eof(self):
        return True

    def readlines(self):
        return []

    def stop(self):
        self.stopped = True

    def join(self):
        self.joined = True


class _Process:
    stdout = object()
    pid = 42


def test_decoder_lifecycle_uses_platform_process_helpers(monkeypatch):
    decoder = decode.SondeDecoder.__new__(decode.SondeDecoder)
    decoder.decoder_command = "decoder 2>/dev/null"
    decoder.decoder_command_2 = None
    decoder.decoder_running = True
    decoder.timeout = 0
    decoder.udp_mode = False
    decoder.experimental_decoder = False
    decoder.log_debug = lambda *args: None
    decoder.log_info = lambda *args: None
    decoder.log_error = lambda *args: None

    popen_calls = []
    terminated = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return _Process()

    monkeypatch.setattr(decode.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(decode, "AsynchronousFileReader", _Reader)
    monkeypatch.setattr(decode.platform, "prepare_shell_command", lambda command: "translated")
    monkeypatch.setattr(decode.platform, "popen_kwargs", lambda: {"creationflags": 512})
    monkeypatch.setattr(decode.platform, "terminate_process_tree", terminated.append)

    decoder.decoder_thread()

    assert popen_calls == [
        (("translated",), {"shell": True, "stdin": None, "stdout": decode.subprocess.PIPE, "creationflags": 512})
    ]
    assert terminated == [decoder.decode_process]
    assert decoder.decoder_running is False


def test_decoder_rejects_windows_percent_command_before_popen(monkeypatch):
    decoder = decode.SondeDecoder.__new__(decode.SondeDecoder)
    decoder.decoder_command = "decoder %AUTORX_SCAN_FREQUENCY%"
    decoder.decoder_command_2 = None
    decoder.decoder_running = True
    decoder.timeout = 0
    decoder.udp_mode = False
    decoder.experimental_decoder = False
    decoder.log_debug = lambda *args: None
    decoder.log_info = lambda *args: None
    decoder.log_error = lambda *args: None

    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(
        decode.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("decoder command must not reach Popen"),
    )

    with pytest.raises(ValueError, match="percent"):
        decoder.decoder_thread()


def test_time_slice_stop_forces_a_hung_decoder_process(monkeypatch):
    class HungThread:
        def __init__(self):
            self.joins = []

        def join(self, timeout=None):
            self.joins.append(timeout)

        def is_alive(self):
            return True

    decoder = decode.SondeDecoder.__new__(decode.SondeDecoder)
    decoder.decoder_running = True
    decoder.decoder = HungThread()
    decoder.decode_process = object()
    decoder.experimental_decoder = False
    decoder.raw_file = None
    decoder.log_error = lambda *args: None
    terminated = []
    monkeypatch.setattr(decode.platform, "terminate_process_tree", terminated.append)

    decoder.stop(join_timeout=0.1)

    assert decoder.decoder.joins == [0.1, 2.0]
    assert terminated == [decoder.decode_process]
