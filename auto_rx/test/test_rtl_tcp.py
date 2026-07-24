import socket
import struct
import threading

import pytest

from autorx.rtl_tcp import RtlTcpClient, RtlTcpConnectionError, RtlTcpProtocolError


class FakeRtlTcpServer:
    def __init__(self, header=b"RTL0" + struct.pack("!II", 0x0BDA, 0x2838)):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._header = header
        self.commands = bytearray()
        self._connection = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            self._connection, _ = self._listener.accept()
            self._connection.sendall(self._header)
            while True:
                chunk = self._connection.recv(1024)
                if not chunk:
                    break
                self.commands.extend(chunk)
        except OSError:
            pass

    def send_iq(self, data, chunks=(1,)):
        self._wait_for_connection()
        offset = 0
        for length in chunks:
            self._connection.sendall(data[offset : offset + length])
            offset += length
        if offset < len(data):
            self._connection.sendall(data[offset:])

    def close_write(self):
        self._wait_for_connection()
        self._connection.shutdown(socket.SHUT_WR)

    def reset_connection(self):
        self._wait_for_connection()
        self._connection.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0)
        )
        self._connection.close()

    def _wait_for_connection(self):
        while self._connection is None:
            threading.Event().wait(0.001)

    def close(self):
        if self._connection is not None:
            self._connection.close()
        self._listener.close()
        self._thread.join(timeout=1)


@pytest.fixture
def rtl_tcp_server():
    server = FakeRtlTcpServer()
    try:
        yield server
    finally:
        server.close()


def test_connect_reads_standard_handshake(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=1)

    handshake = client.connect()

    assert handshake.magic == b"RTL0"
    assert handshake.tuner_type == 0x0BDA
    assert handshake.tuner_gain_count == 0x2838
    client.close()


def test_connect_rejects_non_rtl_tcp_handshake():
    server = FakeRtlTcpServer(header=b"NOPE" + b"\0" * 8)
    client = RtlTcpClient("127.0.0.1", server.port, timeout=1)
    try:
        with pytest.raises(RtlTcpProtocolError, match="RTL0"):
            client.connect()
    finally:
        client.close()
        server.close()


def test_controls_use_standard_rtl_tcp_command_bytes(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=1)
    client.connect()

    client.set_frequency(401_500_000)
    client.set_sample_rate(96_000)
    client.set_gain_mode(manual=True)
    client.set_gain(496)
    client.set_ppm(-12)

    expected = b"".join(
        (
            struct.pack("!BI", 1, 401_500_000),
            struct.pack("!BI", 2, 96_000),
            struct.pack("!BI", 3, 1),
            struct.pack("!BI", 4, 496),
            struct.pack("!Bi", 5, -12),
        )
    )
    for _ in range(100):
        if bytes(rtl_tcp_server.commands) == expected:
            break
        threading.Event().wait(0.001)
    assert bytes(rtl_tcp_server.commands) == expected
    client.close()


def test_read_iq_exactly_reads_and_converts_unsigned_samples(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=1)
    client.connect()
    rtl_tcp_server.send_iq(bytes((0, 128, 127, 255)), chunks=(1, 2))

    assert client.read_iq(2) == struct.pack("<hhhh", -32768, 0, -256, 32512)
    client.close()


def test_read_iq_times_out_when_server_does_not_send_samples(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=0.01)
    client.connect()

    with pytest.raises(socket.timeout):
        client.read_iq(1)
    client.close()


def test_eof_disconnects_client_and_allows_reconnect():
    first = FakeRtlTcpServer()
    second = FakeRtlTcpServer(header=b"RTL0" + struct.pack("!II", 1, 2))
    client = RtlTcpClient("127.0.0.1", first.port, timeout=1)
    try:
        client.connect()
        first.close_write()

        with pytest.raises(RtlTcpConnectionError):
            client.read_iq(1)

        assert client.connected is False
        assert client.handshake is None
        client.port = second.port
        assert client.reconnect().tuner_type == 1
    finally:
        client.close()
        first.close()
        second.close()


def test_read_timeout_disconnects_client_and_allows_reconnect():
    first = FakeRtlTcpServer()
    second = FakeRtlTcpServer(header=b"RTL0" + struct.pack("!II", 1, 2))
    client = RtlTcpClient("127.0.0.1", first.port, timeout=0.01)
    try:
        client.connect()

        with pytest.raises(socket.timeout):
            client.read_iq(1)

        assert client.connected is False
        assert client.handshake is None
        client.port = second.port
        assert client.reconnect().tuner_type == 1
    finally:
        client.close()
        first.close()
        second.close()


def test_send_failure_disconnects_client_and_allows_reconnect():
    first = FakeRtlTcpServer()
    second = FakeRtlTcpServer(header=b"RTL0" + struct.pack("!II", 1, 2))
    client = RtlTcpClient("127.0.0.1", first.port, timeout=1)
    try:
        client.connect()
        first.reset_connection()

        with pytest.raises(OSError):
            client.set_frequency(401_500_000)

        assert client.connected is False
        assert client.handshake is None
        client.port = second.port
        assert client.reconnect().tuner_type == 1
    finally:
        client.close()
        first.close()
        second.close()


def test_reconnect_closes_previous_socket_and_reads_new_handshake():
    first = FakeRtlTcpServer()
    second = FakeRtlTcpServer(header=b"RTL0" + struct.pack("!II", 1, 2))
    client = RtlTcpClient("127.0.0.1", first.port, timeout=1)
    try:
        client.connect()
        client.port = second.port

        handshake = client.reconnect()

        assert handshake.tuner_type == 1
        assert handshake.tuner_gain_count == 2
    finally:
        client.close()
        first.close()
        second.close()


def test_enable_bias_tee_explains_that_base_rtl_tcp_cannot_do_it(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=1)

    with pytest.raises(NotImplementedError, match="base RTL-TCP protocol"):
        client.set_bias_tee(True)


def test_set_agc_mode_uses_the_standard_rtl_tcp_command(rtl_tcp_server):
    client = RtlTcpClient("127.0.0.1", rtl_tcp_server.port, timeout=1)
    client.connect()

    client.set_agc_mode(True)

    expected = struct.pack("!BI", 8, 1)
    for _ in range(100):
        if bytes(rtl_tcp_server.commands) == expected:
            break
        threading.Event().wait(0.001)
    assert bytes(rtl_tcp_server.commands) == expected
    client.close()
