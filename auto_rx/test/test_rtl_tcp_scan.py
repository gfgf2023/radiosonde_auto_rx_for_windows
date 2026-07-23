import numpy as np

from autorx import rtl_tcp_scan
from autorx import sdr_wrappers


def test_plan_scan_segments_covers_400_4_to_403_5_mhz_with_two_2_4_mhz_tunes():
    segments = rtl_tcp_scan.plan_scan_segments(
        400_400_000, 403_500_000, 2_400_000
    )

    assert len(segments) == 2
    assert segments[0].frequency_start == 400_400_000
    assert segments[-1].frequency_stop == 403_500_000
    assert segments[0].center_frequency == 401_600_000
    assert segments[-1].center_frequency == 402_300_000
    assert segments[0].frequency_stop == segments[1].frequency_start


def test_power_spectrum_from_signed_iq_has_a_tone_peak():
    sample_rate = 2_400_000
    tone_offset = 120_000
    samples = np.arange(24_000)
    tone = 24_000 * np.exp(2j * np.pi * tone_offset * samples / sample_rate)
    interleaved = np.empty(tone.size * 2, dtype="<i2")
    interleaved[0::2] = tone.real.astype(np.int16)
    interleaved[1::2] = tone.imag.astype(np.int16)

    frequencies, power, bin_width = rtl_tcp_scan.power_spectrum_from_signed_iq(
        interleaved.tobytes(),
        center_frequency=401_500_000,
        sample_rate=sample_rate,
        step=800,
    )

    peak_frequency = frequencies[np.argmax(power)]
    assert bin_width == 800
    assert abs(peak_frequency - (401_500_000 + tone_offset)) <= bin_width
    assert power.max() > np.median(power) + 20


def test_rtl_tcp_spectrum_uses_client_samples_without_invoking_rtl_power(monkeypatch):
    calls = []

    class Client:
        def __init__(self, host, port, timeout):
            calls.append(("init", host, port, timeout))

        def connect(self):
            calls.append(("connect",))

        def set_frequency(self, value):
            calls.append(("frequency", value))

        def set_sample_rate(self, value):
            calls.append(("sample_rate", value))

        def set_ppm(self, value):
            calls.append(("ppm", value))

        def set_gain_mode(self, value):
            calls.append(("gain_mode", value))

        def set_gain(self, value):
            calls.append(("gain", value))

        def read_iq(self, samples):
            calls.append(("read_iq", samples))
            return np.zeros(samples * 2, dtype="<i2").tobytes()

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(rtl_tcp_scan, "RtlTcpClient", Client)

    frequencies, power, bin_width = rtl_tcp_scan.get_power_spectrum(
        frequency_start=400_400_000,
        frequency_stop=403_500_000,
        step=800,
        integration_time=0,
        sdr_hostname="rtl.example",
        sdr_port=1234,
        ppm=-3,
        gain=12.5,
    )

    assert len(frequencies) == len(power) > 0
    assert bin_width == 800
    assert frequencies[0] >= 400_400_000
    assert frequencies[-1] <= 403_500_000
    assert ("sample_rate", 2_400_000) in calls
    assert any(call[0] == "read_iq" for call in calls)


def test_rtl_tcp_spectrum_splits_total_dwell_time_between_segments(monkeypatch):
    durations = []

    monkeypatch.setattr(
        rtl_tcp_scan,
        "_capture_segment",
        lambda client, segment, sample_rate, step, integration_time: (
            durations.append(integration_time) or np.array([segment.frequency_start]),
            np.array([1.0]),
            step,
        ),
    )

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def set_frequency(self, value):
            pass

        def set_sample_rate(self, value):
            pass

        def set_ppm(self, value):
            pass

        def set_gain_mode(self, value):
            pass

        def close(self):
            pass

    monkeypatch.setattr(rtl_tcp_scan, "RtlTcpClient", Client)

    rtl_tcp_scan.get_power_spectrum(
        frequency_start=400_400_000,
        frequency_stop=403_500_000,
        step=800,
        integration_time=0.5,
        sdr_hostname="rtl.example",
        sdr_port=1234,
        settling_samples=0,
    )

    assert durations == [0.25, 0.25]
    assert sum(durations) == 0.5


def test_rtl_tcp_spectrum_has_no_duplicate_bins_at_segment_boundaries(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def set_frequency(self, value):
            pass

        def set_sample_rate(self, value):
            pass

        def set_ppm(self, value):
            pass

        def set_gain_mode(self, value):
            pass

        def close(self):
            pass

    def capture(client, segment, sample_rate, step, integration_time):
        return (
            np.array([segment.frequency_start, segment.frequency_stop]),
            np.array([1.0, 2.0]),
            step,
        )

    monkeypatch.setattr(rtl_tcp_scan, "RtlTcpClient", Client)
    monkeypatch.setattr(rtl_tcp_scan, "_capture_segment", capture)

    frequencies, _, _ = rtl_tcp_scan.get_power_spectrum(
        frequency_start=400_400_000,
        frequency_stop=403_500_000,
        step=800,
        integration_time=1,
        sdr_hostname="rtl.example",
        sdr_port=1234,
        settling_samples=0,
    )

    assert len(frequencies) == len(set(frequencies))


def test_rtl_tcp_spectrum_discards_bounded_post_tune_iq(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            calls.append("connect")

        def set_frequency(self, value):
            calls.append("frequency")

        def set_sample_rate(self, value):
            calls.append("sample_rate")

        def set_ppm(self, value):
            calls.append("ppm")

        def set_gain_mode(self, value):
            pass

        def read_iq(self, samples):
            calls.append(("read_iq", samples))
            return b""

        def close(self):
            pass

    monkeypatch.setattr(rtl_tcp_scan, "RtlTcpClient", Client)
    monkeypatch.setattr(
        rtl_tcp_scan,
        "_capture_segment",
        lambda *args: (np.array([400_400_000]), np.array([1.0]), 800),
    )

    rtl_tcp_scan.get_power_spectrum(
        frequency_start=400_400_000,
        frequency_stop=400_500_000,
        step=800,
        integration_time=1,
        sdr_hostname="rtl.example",
        sdr_port=1234,
        settling_samples=123,
    )

    assert calls.index(("read_iq", 123)) > calls.index("sample_rate")
    with np.testing.assert_raises(ValueError):
        rtl_tcp_scan.get_power_spectrum(
            frequency_start=400_400_000,
            frequency_stop=400_500_000,
            step=800,
            integration_time=1,
            sdr_hostname="rtl.example",
            sdr_port=1234,
            settling_samples=rtl_tcp_scan.MAX_SETTLING_SAMPLES + 1,
        )


def test_sdr_wrapper_routes_rtl_tcp_spectrum_to_the_native_scanner(monkeypatch):
    expected = (np.array([401_500_000]), np.array([12.0]), 800)
    captured = {}

    def native_scanner(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(rtl_tcp_scan, "get_power_spectrum", native_scanner)
    monkeypatch.setattr(
        sdr_wrappers.autorx_platform,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rtl_power used")),
    )

    assert sdr_wrappers.get_power_spectrum(
        sdr_type="RTL_TCP",
        frequency_start=400_400_000,
        frequency_stop=403_500_000,
        step=800,
        integration_time=2,
        sdr_hostname="rtl.example",
        sdr_port=1234,
    ) == expected
    assert captured["sdr_hostname"] == "rtl.example"


def test_sdr_wrapper_returns_no_spectrum_for_rtl_tcp_transport_failure(monkeypatch, caplog):
    from autorx.rtl_tcp import RtlTcpConnectionError, RtlTcpProtocolError

    monkeypatch.setattr(
        rtl_tcp_scan,
        "get_power_spectrum",
        lambda **kwargs: (_ for _ in ()).throw(RtlTcpConnectionError("offline")),
    )

    assert sdr_wrappers.get_power_spectrum(sdr_type="RTL_TCP") == (None, None, None)
    assert "RTL-TCP spectrum capture failed: offline" in caplog.text

    monkeypatch.setattr(
        rtl_tcp_scan,
        "get_power_spectrum",
        lambda **kwargs: (_ for _ in ()).throw(RtlTcpProtocolError("bad header")),
    )

    assert sdr_wrappers.get_power_spectrum(sdr_type="RTL_TCP") == (None, None, None)
    assert "RTL-TCP spectrum capture failed: bad header" in caplog.text


def test_sdr_wrapper_preserves_rtl_tcp_invalid_argument_errors(monkeypatch):
    monkeypatch.setattr(
        rtl_tcp_scan,
        "get_power_spectrum",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("invalid scan range")),
    )

    with np.testing.assert_raises_regex(ValueError, "invalid scan range"):
        sdr_wrappers.get_power_spectrum(sdr_type="RTL_TCP")
