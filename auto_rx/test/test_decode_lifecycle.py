from autorx import decode


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
    monkeypatch.setattr(decode.platform, "translate_command", lambda command: "translated")
    monkeypatch.setattr(decode.platform, "popen_kwargs", lambda: {"creationflags": 512})
    monkeypatch.setattr(decode.platform, "terminate_process_tree", terminated.append)

    decoder.decoder_thread()

    assert popen_calls == [
        (("translated",), {"shell": True, "stdin": None, "stdout": decode.subprocess.PIPE, "creationflags": 512})
    ]
    assert terminated == [decoder.decode_process]
    assert decoder.decoder_running is False
