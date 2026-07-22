"""Native spectrum capture for a standard RTL-TCP endpoint."""

from dataclasses import dataclass
import math

import numpy as np

from .rtl_tcp import RtlTcpClient


DEFAULT_SAMPLE_RATE = 2_400_000


@dataclass(frozen=True)
class ScanSegment:
    """One tuner setting and its non-overlapping output portion."""

    center_frequency: int
    frequency_start: int
    frequency_stop: int


def plan_scan_segments(frequency_start, frequency_stop, sample_rate=DEFAULT_SAMPLE_RATE):
    """Split a scan range into overlapping tuner bandwidths without output gaps."""
    if frequency_stop <= frequency_start:
        raise ValueError("frequency_stop must be greater than frequency_start")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    count = math.ceil((frequency_stop - frequency_start) / sample_rate)
    if count == 1:
        centers = [(frequency_start + frequency_stop) / 2]
    else:
        centers = np.linspace(
            frequency_start + sample_rate / 2,
            frequency_stop - sample_rate / 2,
            count,
        )

    boundaries = [frequency_start]
    boundaries.extend((centers[index] + centers[index + 1]) / 2 for index in range(count - 1))
    boundaries.append(frequency_stop)
    return [
        ScanSegment(
            center_frequency=round(centers[index]),
            frequency_start=round(boundaries[index]),
            frequency_stop=round(boundaries[index + 1]),
        )
        for index in range(count)
    ]


def _complex_iq(signed_iq):
    values = np.frombuffer(signed_iq, dtype="<i2")
    if len(values) % 2:
        raise ValueError("RTL-TCP IQ data must contain complete I/Q pairs")
    return values[0::2].astype(np.float64) + 1j * values[1::2]


def _fft_size(sample_rate, step):
    if step <= 0:
        raise ValueError("step must be positive")
    size = max(2, round(sample_rate / step))
    return size + (size % 2)


def _linear_periodogram(samples, sample_rate, step):
    fft_size = _fft_size(sample_rate, step)
    frames = len(samples) // fft_size
    if not frames:
        raise ValueError("not enough IQ samples for one spectrum frame")
    samples = samples[: frames * fft_size].reshape(frames, fft_size)
    window = np.hanning(fft_size)
    spectra = np.fft.fftshift(np.fft.fft(samples * window, axis=1), axes=1)
    power = np.mean(np.abs(spectra) ** 2, axis=0) / np.sum(window**2)
    offsets = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1 / sample_rate))
    return offsets, power, sample_rate / fft_size


def power_spectrum_from_signed_iq(signed_iq, center_frequency, sample_rate, step):
    """Return a dB periodogram for signed little-endian 16-bit I/Q samples."""
    offsets, power, bin_width = _linear_periodogram(
        _complex_iq(signed_iq), sample_rate, step
    )
    frequencies = offsets + center_frequency
    return frequencies, 10 * np.log10(np.maximum(power, np.finfo(float).tiny)), bin_width


def _configure_client(client, center_frequency, sample_rate, ppm, gain):
    client.connect()
    client.set_frequency(int(center_frequency))
    client.set_sample_rate(int(sample_rate))
    client.set_ppm(int(ppm))
    if gain is None or gain < 0:
        client.set_gain_mode(False)
    else:
        client.set_gain_mode(True)
        client.set_gain(round(gain * 10))


def _capture_segment(client, segment, sample_rate, step, integration_time):
    fft_size = _fft_size(sample_rate, step)
    frame_count = max(1, math.ceil(integration_time * sample_rate / fft_size))
    frames_per_read = max(1, min(64, 262_144 // (fft_size * 4)))
    accumulated_power = None
    completed_frames = 0

    while completed_frames < frame_count:
        frames = min(frames_per_read, frame_count - completed_frames)
        offsets, power, bin_width = _linear_periodogram(
            _complex_iq(client.read_iq(frames * fft_size)), sample_rate, step
        )
        if accumulated_power is None:
            accumulated_power = power * frames
        else:
            accumulated_power += power * frames
        completed_frames += frames

    frequencies = offsets + segment.center_frequency
    mask = (frequencies >= segment.frequency_start) & (
        frequencies <= segment.frequency_stop
    )
    return frequencies[mask], accumulated_power[mask] / completed_frames, bin_width


def get_power_spectrum(
    frequency_start,
    frequency_stop,
    step,
    integration_time,
    sdr_hostname,
    sdr_port,
    ppm=0,
    gain=None,
    bias=False,
    sample_rate=DEFAULT_SAMPLE_RATE,
):
    """Tune one RTL-TCP endpoint sequentially and return its measured PSD."""
    if bias:
        raise ValueError("Bias-T is not supported by the base RTL-TCP protocol")

    frequencies = []
    powers = []
    bin_width = None
    for segment in plan_scan_segments(frequency_start, frequency_stop, sample_rate):
        client = RtlTcpClient(sdr_hostname, sdr_port, timeout=integration_time + 10)
        try:
            _configure_client(client, segment.center_frequency, sample_rate, ppm, gain)
            segment_freq, segment_power, bin_width = _capture_segment(
                client, segment, sample_rate, step, integration_time
            )
            frequencies.append(segment_freq)
            powers.append(segment_power)
        finally:
            client.close()

    if not frequencies:
        return None, None, None
    return np.concatenate(frequencies), 10 * np.log10(
        np.maximum(np.concatenate(powers), np.finfo(float).tiny)
    ), bin_width
