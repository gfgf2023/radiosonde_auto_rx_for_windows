"""Small client for the base rtl_tcp wire protocol.

The base protocol is a TCP stream with a twelve-byte server header followed by
unsigned 8-bit interleaved I/Q samples.  This module intentionally contains no
auto_rx configuration or decoder integration.
"""

from dataclasses import dataclass
import socket
import struct
from typing import Optional


RTL_TCP_MAGIC = b"RTL0"
RTL_TCP_HANDSHAKE_SIZE = 12

SET_FREQUENCY = 0
SET_SAMPLE_RATE = 1
SET_GAIN_MODE = 2
SET_GAIN = 3
SET_PPM = 4


class RtlTcpProtocolError(ConnectionError):
    """The peer did not speak the standard rtl_tcp protocol."""


class RtlTcpConnectionError(ConnectionError):
    """An operation requiring an RTL-TCP connection was attempted disconnected."""


@dataclass(frozen=True)
class RtlTcpHandshake:
    magic: bytes
    tuner_type: int
    tuner_gain_count: int


class RtlTcpClient:
    """Connect to a standard rtl_tcp server and exchange IQ samples.

    Gain values are passed in the tenths-of-a-dB units used by the rtl_tcp
    protocol.  ``read_iq`` returns signed little-endian 16-bit I/Q pairs,
    which are compatible with the existing auto_rx decoder input format.
    """

    def __init__(self, host: str, port: int = 1234, timeout: Optional[float] = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self.handshake: Optional[RtlTcpHandshake] = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> RtlTcpHandshake:
        """Open the socket and read the mandatory twelve-byte server header."""
        self.close()
        connection = socket.create_connection((self.host, self.port), self.timeout)
        connection.settimeout(self.timeout)
        self._socket = connection
        try:
            header = self._read_exact(RTL_TCP_HANDSHAKE_SIZE)
            magic, tuner_type, tuner_gain_count = struct.unpack("!4sII", header)
            if magic != RTL_TCP_MAGIC:
                raise RtlTcpProtocolError(
                    "RTL-TCP server handshake must begin with b'RTL0'"
                )
            self.handshake = RtlTcpHandshake(magic, tuner_type, tuner_gain_count)
            return self.handshake
        except Exception:
            self.close()
            raise

    def reconnect(self) -> RtlTcpHandshake:
        """Discard the current connection and establish a fresh one."""
        return self.connect()

    def close(self) -> None:
        """Close the socket, if any, and clear the cached server information."""
        connection, self._socket = self._socket, None
        self.handshake = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    disconnect = close

    def set_frequency(self, frequency_hz: int) -> None:
        self._send_unsigned_command(SET_FREQUENCY, frequency_hz)

    set_center_frequency = set_frequency

    def set_sample_rate(self, sample_rate_hz: int) -> None:
        self._send_unsigned_command(SET_SAMPLE_RATE, sample_rate_hz)

    def set_gain_mode(self, manual: bool) -> None:
        self._send_unsigned_command(SET_GAIN_MODE, int(bool(manual)))

    def set_gain(self, gain_tenth_db: int) -> None:
        self._send_unsigned_command(SET_GAIN, gain_tenth_db)

    def set_ppm(self, ppm: int) -> None:
        if not -(2**31) <= ppm < 2**31:
            raise ValueError("ppm must fit in a signed 32-bit integer")
        self._send_command(struct.pack("!Bi", SET_PPM, ppm))

    def set_bias_tee(self, enabled: bool) -> None:
        """Reject Bias-T requests because it is not in the base RTL-TCP spec."""
        raise NotImplementedError(
            "Bias-T is not supported by the base RTL-TCP protocol; "
            "server-specific extensions are not portable."
        )

    def read_iq(self, samples: int) -> bytes:
        """Read ``samples`` complex samples as signed little-endian 16-bit IQ."""
        if samples < 0:
            raise ValueError("samples must not be negative")
        raw_iq = self._read_exact(samples * 2)
        converted = bytearray(samples * 4)
        for index, value in enumerate(raw_iq):
            struct.pack_into("<h", converted, index * 2, (value - 128) << 8)
        return bytes(converted)

    def _send_unsigned_command(self, command: int, value: int) -> None:
        if not 0 <= value < 2**32:
            raise ValueError("RTL-TCP control values must fit in an unsigned 32-bit integer")
        self._send_command(struct.pack("!BI", command, value))

    def _send_command(self, command: bytes) -> None:
        connection = self._require_socket()
        try:
            connection.sendall(command)
        except OSError:
            self.close()
            raise

    def _read_exact(self, size: int) -> bytes:
        connection = self._require_socket()
        chunks = bytearray()
        try:
            while len(chunks) < size:
                chunk = connection.recv(size - len(chunks))
                if not chunk:
                    raise RtlTcpConnectionError(
                        "RTL-TCP server closed the connection before completing a read"
                    )
                chunks.extend(chunk)
        except OSError:
            self.close()
            raise
        return bytes(chunks)

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RtlTcpConnectionError("RTL-TCP client is not connected")
        return self._socket


# Retain a conventional all-caps spelling for callers using the protocol name.
RTL_TCPClient = RtlTcpClient
