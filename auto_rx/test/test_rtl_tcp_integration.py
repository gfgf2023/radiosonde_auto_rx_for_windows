import io
from pathlib import Path
import subprocess
import sys

import pytest

from autorx import config
from autorx import scan
from autorx import sdr_wrappers
from autorx.rtl_tcp_rx import configure_client, stream_iq


class FakeBridgeClient:
    def __init__(self, chunk):
        self.chunk = chunk
        self.calls = []

    def connect(self):
        self.calls.append(("connect",))

    def set_frequency(self, value):
        self.calls.append(("frequency", value))

    def set_sample_rate(self, value):
        self.calls.append(("sample_rate", value))

    def set_ppm(self, value):
        self.calls.append(("ppm", value))

    def set_gain_mode(self, value):
        self.calls.append(("gain_mode", value))

    def set_gain(self, value):
        self.calls.append(("gain", value))

    def set_agc_mode(self, value):
        self.calls.append(("agc_mode", value))

    def read_iq(self, samples):
        self.calls.append(("read_iq", samples))
        if self.chunk is None:
            raise ConnectionError("server closed")
        chunk, self.chunk = self.chunk, None
        return chunk


def test_bridge_configures_manual_gain_and_forwards_signed_iq():
    client = FakeBridgeClient(b"\x00\x80\x00\x00")
    output = io.BytesIO()

    configure_client(
        client,
        frequency=401_500_000,
        sample_rate=96_000,
        ppm=-12,
        gain=49.6,
    )
    with pytest.raises(ConnectionError, match="server closed"):
        stream_iq(client, output, samples_per_chunk=1)

    assert client.calls == [
        ("connect",),
        ("frequency", 401_500_000),
        ("sample_rate", 96_000),
        ("ppm", -12),
        ("gain_mode", True),
        ("gain", 496),
        ("read_iq", 1),
        ("read_iq", 1),
    ]
    assert output.getvalue() == b"\x00\x80\x00\x00"


def test_bridge_enables_baseband_agc_for_gain_minus_two():
    client = FakeBridgeClient(None)

    configure_client(
        client,
        frequency=401_500_000,
        sample_rate=96_000,
        ppm=0,
        gain=-2,
    )

    assert client.calls == [
        ("connect",),
        ("frequency", 401_500_000),
        ("sample_rate", 96_000),
        ("ppm", 0),
        ("gain_mode", False),
        ("agc_mode", True),
    ]
def test_rtl_tcp_bridge_cli_exposes_required_receiver_options():
    result = subprocess.run(
        [sys.executable, "-m", "autorx.rtl_tcp_rx", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0
    assert "--host" in result.stdout
    assert "--sample-rate" in result.stdout


def test_rtl_tcp_iq_command_uses_active_interpreter_and_rejects_bias(monkeypatch):
    monkeypatch.setattr(sdr_wrappers.sys, "executable", "/opt/auto-rx/bin/python3")

    command = sdr_wrappers.get_sdr_iq_cmd(
        sdr_type="RTL_TCP",
        frequency=401_500_000,
        sample_rate=96_000,
        sdr_hostname="rtl.example",
        sdr_port=1234,
        ppm=-12,
        gain=49.6,
    )

    assert "/opt/auto-rx/bin/python3 -m autorx.rtl_tcp_rx" in command
    assert "--host rtl.example --port 1234" in command
    assert "--frequency 401500000 --sample-rate 288000" in command
    assert "--ppm -12 --gain 49.6" in command
    assert "./iq_dec --bo 16 --IFbw 96 - 288000 16" in command

    with pytest.raises(ValueError, match="Bias-T"):
        sdr_wrappers.get_sdr_iq_cmd(
            sdr_type="RTL_TCP",
            frequency=401_500_000,
            sample_rate=96_000,
            bias=True,
        )


@pytest.mark.parametrize(
    ("decoder_rate", "receiver_rate"),
    ((48_000, 240_000), (50_000, 250_000), (96_000, 288_000), (220_000, 440_000)),
)
def test_rtl_tcp_iq_command_resamples_low_decoder_rates_locally(
    monkeypatch, decoder_rate, receiver_rate
):
    monkeypatch.setattr(sdr_wrappers.sys, "executable", "/opt/auto-rx/bin/python3")

    command = sdr_wrappers.get_sdr_iq_cmd(
        sdr_type="RTL_TCP",
        frequency=400_438_000,
        sample_rate=decoder_rate,
        sdr_hostname="rtl.example",
        sdr_port=1234,
    )

    assert f"--sample-rate {receiver_rate}" in command
    assert (
        f"./iq_dec --bo 16 --IFbw {decoder_rate // 1000} "
        f"- {receiver_rate} 16"
    ) in command


def test_rtl_tcp_iq_command_quotes_windows_venv_interpreter(monkeypatch):
    interpreter = r"C:\Program Files\auto_rx\.venv\Scripts\python.exe"
    monkeypatch.setattr(sdr_wrappers.sys, "executable", interpreter)
    monkeypatch.setattr(sdr_wrappers.autorx_platform, "is_windows", lambda: True)

    command = sdr_wrappers.get_sdr_iq_cmd(
        sdr_type="RTL_TCP",
        frequency=401_500_000,
        sample_rate=96_000,
        sdr_hostname="rtl.example",
        sdr_port=1234,
    )

    assert command.startswith(f'"{interpreter}" -m autorx.rtl_tcp_rx ')


def test_rtl_tcp_fm_command_demodulates_the_bridge_iq_with_iq_dec(monkeypatch):
    monkeypatch.setattr(sdr_wrappers.sys, "executable", "/opt/auto-rx/bin/python3")

    command = sdr_wrappers.get_sdr_fm_cmd(
        sdr_type="RTL_TCP",
        frequency=401_500_000,
        filter_bandwidth=15_000,
        sample_rate=48_000,
        sdr_hostname="rtl.example",
        sdr_port=1234,
    )

    assert "/opt/auto-rx/bin/python3 -m autorx.rtl_tcp_rx" in command
    assert "--sample-rate 240000" in command
    assert "./iq_dec --bo 16 --IFbw 48 --FM - 240000 16" in command
    assert "sox -t raw -r 48000" in command
    assert "rtl_fm" not in command


def test_detect_sonde_forwards_rtl_tcp_endpoint_to_lms6_fm_source(monkeypatch):
    captured = {}

    def get_fm_command(**kwargs):
        captured.update(kwargs)
        return "source | "

    monkeypatch.setattr(scan, "get_sdr_fm_cmd", get_fm_command)
    monkeypatch.setattr(scan, "get_sdr_name", lambda *args, **kwargs: "RTL-TCP")
    monkeypatch.setattr(scan, "shutdown_sdr", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scan.autorx_platform,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, args[0], output=b"")
        ),
    )

    assert scan.detect_sonde(
        1_680_000_000,
        sdr_type="RTL_TCP",
        sdr_hostname="rtl.example",
        sdr_port=2345,
    ) == (None, 0.0)

    assert captured["sdr_type"] == "RTL_TCP"
    assert captured["sdr_hostname"] == "rtl.example"
    assert captured["sdr_port"] == 2345


def test_rtl_tcp_config_does_not_require_local_rtl_sdr(tmp_path, monkeypatch):
    source = Path(config.__file__).resolve().parents[1] / "station.cfg.example"
    cfg = tmp_path / "station.cfg"
    cfg.write_text(
        source.read_text()
        .replace("sdr_type = RTLSDR", "sdr_type = RTL_TCP")
        .replace("sdr_hostname = localhost", "sdr_hostname = rtl.example")
        .replace("sdr_port = 5555", "sdr_port = 1234")
    )
    monkeypatch.setattr(config, "test_sdr", lambda **kwargs: True)
    monkeypatch.setattr(
        config.autorx_platform,
        "executable_exists",
        lambda executable: pytest.fail("RTL_TCP must not require rtl_sdr"),
    )

    result = config.read_auto_rx_config(str(cfg))

    assert result["sdr_type"] == "RTL_TCP"


def test_rtl_tcp_config_rejects_multiple_receivers_for_one_global_tuner(
    tmp_path, monkeypatch
):
    source = Path(config.__file__).resolve().parents[1] / "station.cfg.example"
    cfg = tmp_path / "station.cfg"
    cfg.write_text(
        source.read_text().replace("sdr_type = RTLSDR", "sdr_type = RTL_TCP").replace(
            "sdr_quantity = 1", "sdr_quantity = 2"
        ).replace("sdr_hostname = localhost", "sdr_hostname = rtl.example").replace(
            "sdr_port = 5555", "sdr_port = 1234"
        )
    )
    calls = []

    def test_endpoint(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(config, "test_sdr", test_endpoint)

    result = config.read_auto_rx_config(str(cfg))

    assert result is None
    assert calls == []


def test_rtl_tcp_config_rejects_bias_tee(tmp_path, monkeypatch):
    source = Path(config.__file__).resolve().parents[1] / "station.cfg.example"
    cfg = tmp_path / "station.cfg"
    cfg.write_text(
        source.read_text()
        .replace("sdr_type = RTLSDR", "sdr_type = RTL_TCP")
        .replace("bias = False", "bias = True")
    )
    monkeypatch.setattr(config, "test_sdr", lambda **kwargs: True)

    assert config.read_auto_rx_config(str(cfg)) is None
