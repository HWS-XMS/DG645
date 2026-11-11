from __future__ import annotations

from .enums import ErrorCode


class DG645Error(Exception):
    """Base class for all errors raised by this library."""


class DG645CommunicationError(DG645Error):
    """The serial link failed: port not available, timeout, malformed reply."""


class DG645ResponseError(DG645Error):
    """The instrument replied with something the manual does not allow for this query."""


class DG645InstrumentError(DG645Error):
    """The instrument reported errors (LERR?) after a command, or refused a request."""

    def __init__(self, message: str, errors: tuple[ErrorCode, ...] = ()):
        if errors:
            message += ": " + "; ".join(f"{e.value} {e.name} ({e.description})" for e in errors)
        super().__init__(message)
        self.errors = errors


class DG645VerificationError(DG645Error):
    """Read-back after a set command returned a different value than was sent."""

    def __init__(self, setting: str, expected: object, actual: object):
        super().__init__(f"{setting}: sent {expected!r}, instrument reports {actual!r}")
        self.setting = setting
        self.expected = expected
        self.actual = actual


class DG645ModeError(DG645Error):
    """The setting is not available in the instrument's current mode."""
