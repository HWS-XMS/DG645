"""SerialTransport against a stubbed pyserial port (no hardware needed)."""

import pytest
import serial

from dg645 import BaudRate, DG645CommunicationError, SerialTransport


class FakeSerial:
    """``incoming`` is what is already in the input buffer; ``reply`` arrives after the next write."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.timeout = kwargs.get("timeout")
        self.written = b""
        self.incoming = b""
        self.reply = b""
        self.read_timeouts = []

    def reset_input_buffer(self):
        self.incoming = b""

    def write(self, data):
        self.written += data
        self.incoming += self.reply
        self.reply = b""

    def read_until(self, terminator):
        self.read_timeouts.append(self.timeout)
        line, sep, rest = self.incoming.partition(terminator)
        if not sep:  # emulate timeout: return what's there
            self.incoming = b""
            return line
        self.incoming = rest
        return line + sep

    def close(self):
        pass


@pytest.fixture
def port(monkeypatch):
    created = []

    def factory(**kwargs):
        created.append(FakeSerial(**kwargs))
        return created[-1]

    monkeypatch.setattr(serial, "Serial", factory)
    transport = SerialTransport("/dev/ttyUSB0", BaudRate.B19200)
    return transport, created[0]


def test_line_settings_match_manual(port):
    _, fake = port
    assert fake.kwargs["baudrate"] == 19200
    assert fake.kwargs["bytesize"] == serial.EIGHTBITS
    assert fake.kwargs["parity"] == serial.PARITY_NONE
    assert fake.kwargs["stopbits"] == serial.STOPBITS_ONE
    assert fake.kwargs["rtscts"] is True


def test_write_appends_lf(port):
    transport, fake = port
    transport.write("*RST")
    assert fake.written == b"*RST\n"


def test_query_strips_crlf(port):
    transport, fake = port
    fake.reply = b"2,+0.001000000000\r\n"
    assert transport.query("DLAY?3") == "2,+0.001000000000"
    assert fake.written == b"DLAY?3\n"


def test_query_timeout_raises(port):
    transport, fake = port
    fake.reply = b"partial"
    with pytest.raises(DG645CommunicationError):
        transport.query("*IDN?")


def test_custom_terminator(port):
    transport, fake = port
    transport.set_response_terminator(b"\n")
    fake.reply = b"1\n"
    assert transport.query("LOCK?") == "1"


def test_command_length_limit(port):
    transport, _ = port
    with pytest.raises(ValueError):
        transport.write("X" * 255)


def test_baud_rate_must_be_enum(monkeypatch):
    monkeypatch.setattr(serial, "Serial", FakeSerial)
    with pytest.raises(TypeError):
        SerialTransport("/dev/ttyUSB0", 9600)


def test_stale_reply_is_discarded_before_query(port):
    transport, fake = port
    fake.incoming = b"0\r\n"  # late reply to an earlier, timed-out query
    fake.reply = b"DG645 reply\r\n"
    assert transport.query("*IDN?") == "DG645 reply"


def test_query_timeout_override_is_restored(port):
    transport, fake = port
    fake.reply = b"0\r\n"
    assert transport.query("*TST?", timeout_s=300.0) == "0"
    fake.reply = b"1\r\n"
    transport.query("*OPC?")
    assert fake.read_timeouts == [300.0, 1.0]
    assert fake.timeout == 1.0
