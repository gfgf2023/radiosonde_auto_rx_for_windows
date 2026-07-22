import importlib.util
from pathlib import Path

from autorx import platform


def _load_snr_test():
    path = Path(__file__).resolve().parents[1] / "utils" / "snr_test.py"
    spec = importlib.util.spec_from_file_location("snr_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snr_demod_uses_platform_shell_runner(monkeypatch):
    snr_test = _load_snr_test()
    calls = []

    class Result:
        stdout = ""

    monkeypatch.setattr(
        snr_test.autorx_platform,
        "run_command",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    assert snr_test.run_demod("sample.bin", "RS92") == 1
    assert calls[0][0] == (snr_test.RS92_DEMOD + " < sample.bin",)
    assert calls[0][1]["shell"] is True
    assert calls[0][1]["check"] is True
    assert calls[0][1]["stdout"] == platform.subprocess.PIPE
