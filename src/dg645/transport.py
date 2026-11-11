"""RS-232 transport for the DG645 (pyserial).

Line settings are fixed by the instrument (manual p. 42): 8 data bits, no parity,
1 stop bit, RTS/CTS hardware flow control. Only the baud rate is configurable.
Commands are terminated with <LF>; replies end with <CR><LF> unless changed via XTRM.
"""

from __future__ import annotations

import threading
from typing import Protocol

import serial

from .enums import BaudRate
from .errors import DG645CommunicationError

COMMAND_TERMINATOR = b"\n"
DEFAULT_RESPONSE_TERMINATOR = b"\r\n"
MAX_COMMAND_BYTES = 255  # input buffer size, manual p. 44


class Transport(Protocol):
    """What the API needs from a connection. Lets tests substitute a fake."""

    def write(self, command: str) -> None: ...
    def query(self, command: str, timeout_s: float | None = None) -> str: ...
    def set_response_terminator(self, terminator: bytes) -> None: ...
    def close(self) -> None: ...


class SerialTransport:
    def __init__(
        self,
        port: str,
        baud_rate: BaudRate = BaudRate.B9600,
        timeout_s: float = 1.0,
    ):
        if not isinstance(baud_rate, BaudRate):
            raise TypeError(f"baud_rate must be a BaudRate, got {baud_rate!r}")
        self._response_terminator = DEFAULT_RESPONSE_TERMINATOR
        self._lock = threading.Lock()
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baud_rate.value,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                rtscts=True,
                timeout=timeout_s,
                write_timeout=timeout_s,
            )
        except serial.SerialException as e:
            raise DG645CommunicationError(f"Could not open {port}: {e}") from e
        self._serial.reset_input_buffer()

    def write(self, command: str) -> None:
        with self._lock:
            self._send(command)

    def query(self, command: str, timeout_s: float | None = None) -> str:
        """Send ``command`` and return its reply. ``timeout_s`` overrides the default for this call."""
        with self._lock:
            # A late reply to an earlier, timed-out query must not be taken as this one's.
            self._serial.reset_input_buffer()
            self._send(command)
            if timeout_s is None:
                raw = self._serial.read_until(self._response_terminator)
            else:
                default = self._serial.timeout
                self._serial.timeout = timeout_s
                try:
                    raw = self._serial.read_until(self._response_terminator)
                finally:
                    self._serial.timeout = default
        if not raw.endswith(self._response_terminator):
            raise DG645CommunicationError(f"Timed out waiting for reply to {command!r} (got {raw!r})")
        return raw[: -len(self._response_terminator)].decode("ascii")

    def set_response_terminator(self, terminator: bytes) -> None:
        self._response_terminator = terminator

    def close(self) -> None:
        self._serial.close()

    def _send(self, command: str) -> None:
        data = command.encode("ascii") + COMMAND_TERMINATOR
        if len(data) > MAX_COMMAND_BYTES:
            raise ValueError(f"Command exceeds {MAX_COMMAND_BYTES} bytes: {command!r}")
        try:
            self._serial.write(data)
        except serial.SerialException as e:
            raise DG645CommunicationError(f"Write of {command!r} failed: {e}") from e
