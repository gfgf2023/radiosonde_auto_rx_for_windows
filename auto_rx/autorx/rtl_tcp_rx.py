"""Bridge standard rtl_tcp IQ samples into the auto_rx decoder format."""

import argparse
import sys

from .rtl_tcp import RtlTcpClient


DEFAULT_CHUNK_SAMPLES = 16_384
DEFAULT_STREAM_TIMEOUT = 60


def configure_client(client, frequency, sample_rate, ppm, gain):
    """Connect and apply the receiver controls required for one IQ stream."""
    client.connect()
    client.set_frequency(frequency)
    client.set_sample_rate(sample_rate)
    client.set_ppm(ppm)
    if gain < 0:
        client.set_gain_mode(False)
        if gain == -2:
            client.set_agc_mode(True)
    else:
        client.set_gain_mode(True)
        client.set_gain(round(gain * 10))


def stream_iq(client, output, samples_per_chunk=DEFAULT_CHUNK_SAMPLES):
    """Write signed little-endian 16-bit IQ chunks until the peer disconnects."""
    while True:
        output.write(client.read_iq(samples_per_chunk))
        output.flush()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read signed 16-bit IQ from a standard rtl_tcp server."
    )
    parser.add_argument("--host", required=True, help="RTL-TCP server hostname")
    parser.add_argument("--port", type=int, default=1234, help="RTL-TCP server port")
    parser.add_argument("--frequency", type=int, required=True, help="Centre frequency in Hz")
    parser.add_argument("--sample-rate", type=int, required=True, help="Sample rate in Hz")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_STREAM_TIMEOUT,
        help="Socket read timeout in seconds (default: 60)",
    )
    parser.add_argument("--ppm", type=int, default=0, help="Frequency correction in ppm")
    parser.add_argument(
        "--gain",
        type=float,
        default=-1,
        help="Tuner gain in dB; a negative value enables tuner AGC",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = RtlTcpClient(args.host, args.port, timeout=args.timeout)
    try:
        configure_client(
            client,
            frequency=args.frequency,
            sample_rate=args.sample_rate,
            ppm=args.ppm,
            gain=args.gain,
        )
        stream_iq(client, sys.stdout.buffer)
    except BrokenPipeError:
        return 0
    except (ConnectionError, OSError, ValueError) as error:
        print(f"RTL-TCP bridge: {error}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
