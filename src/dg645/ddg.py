"""High-level DG645 driver built on :class:`dg645.api.DG645Api`.

What this layer adds to the API
-------------------------------
* Error checking: after every set command the error queue (LERR?) is read; any
  entry raises :class:`DG645InstrumentError` with the codes.
* Optional read-back (``verify=True``): every set is followed by its query and
  compared with the value actually sent (after rounding).
* Connection handling: identification check, ``*CLS``, optional self test, lock
  against other interfaces (LOCK?) and the front panel (REMT). ``close()`` undoes
  the locks (UNLK?, LCAL).
* Thread safety: one reentrant lock keeps "set, check errors, read back" together.
* Holdoff and prescaling are refused unless advanced triggering is on, because
  switching it on activates whatever values are stored (pp. 23–25).

Settings are properties; the less common commands (step sizes, display,
interface configuration, ...) remain available through :attr:`DigitalDelayGenerator.api`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import TypeVar

from .api import DelaySetting, DG645Api, Identification
from .enums import (
    BaudRate,
    BurstT0Mode,
    Channel,
    ErrorCode,
    Inhibit,
    InstrumentStatus,
    Output,
    Polarity,
    Prescaler,
    State,
    Timebase,
    TriggerSource,
)
from .errors import (
    DG645CommunicationError,
    DG645InstrumentError,
    DG645ModeError,
    DG645VerificationError,
)
from .transport import SerialTransport, Transport

T = TypeVar("T")

EXPECTED_MODEL = "DG645"
DELAY_CHANNELS = (Channel.A, Channel.B, Channel.C, Channel.D, Channel.E, Channel.F, Channel.G, Channel.H)


class DigitalDelayGenerator:
    """A connected DG645. Use as a context manager or call :meth:`close`.

    ``self_test=True`` runs ``*TST?`` on connect. The instrument resets to default
    settings afterwards (p. 35), so it runs before anything is configured.
    """

    def __init__(
        self,
        port: str,
        baud_rate: BaudRate = BaudRate.B9600,
        *,
        timeout_s: float = 1.0,
        verify: bool = False,
        self_test: bool = False,
    ):
        self._connect(SerialTransport(port, baud_rate, timeout_s), verify, self_test)

    @classmethod
    def from_transport(
        cls, transport: Transport, *, verify: bool = False, self_test: bool = False
    ) -> DigitalDelayGenerator:
        """Connect over an already opened transport (e.g. a fake in tests)."""
        ddg = cls.__new__(cls)
        ddg._connect(transport, verify, self_test)
        return ddg

    def _connect(self, transport: Transport, verify: bool, self_test: bool) -> None:
        self._transport = transport
        self._api = DG645Api(transport)
        self._verify = verify
        self._lock = threading.RLock()
        self._closed = False
        self._locked = False
        try:
            self._identification = self._api.identify()
            if self._identification.model != EXPECTED_MODEL:
                raise DG645CommunicationError(
                    f"Expected a {EXPECTED_MODEL}, found {self._identification.model!r}"
                )
            self._api.clear_status()
            if self_test:
                self.self_test()
            if not self._api.request_lock():
                raise DG645InstrumentError("Lock refused: another interface holds the instrument lock")
            self._locked = True
            self._api.go_to_remote()
            self._raise_on_errors("connect")
        except BaseException:
            self.close()
            raise
        self.trigger = Trigger(self)
        self.burst = Burst(self)
        self.channels: Mapping[Channel, DelayChannel] = MappingProxyType(
            {c: DelayChannel(self, c) for c in DELAY_CHANNELS}
        )
        self.outputs: Mapping[Output, OutputControl] = MappingProxyType(
            {o: OutputControl(self, o) for o in Output}
        )

    # ----- Connection -----------------------------------------------------------

    def close(self) -> None:
        """Release the lock, return to front-panel control and close the port. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._locked:
                    self._api.release_lock()
                    self._api.go_to_local()
            finally:
                self._transport.close()

    def __enter__(self) -> DigitalDelayGenerator:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def api(self) -> DG645Api:
        """The command layer, for everything not covered here. No error checking."""
        return self._api

    @property
    def identification(self) -> Identification:
        """*IDN? as read on connect."""
        return self._identification

    @property
    def verify(self) -> bool:
        return self._verify

    # ----- Instrument-wide actions ----------------------------------------------

    def reset(self) -> None:
        """*RST — factory default settings."""
        self._command("*RST", self._api.reset)

    def save(self, slot: int) -> None:
        """*SAV — store settings in slot 1–9."""
        self._command("*SAV", lambda: self._api.save_settings(slot))

    def recall(self, slot: int) -> None:
        """*RCL — slot 0 = factory defaults, 1–9 = user."""
        self._command("*RCL", lambda: self._api.recall_settings(slot))

    def fire(self) -> None:
        """*TRG — fire a single shot, or arm an external single shot."""
        self._command("*TRG", self._api.trigger)

    def wait_until_complete(self, timeout_s: float | None = None) -> None:
        """*OPC? — block until all prior commands have completed."""
        with self._lock:
            if not self._api.query_operation_complete(timeout_s):
                raise DG645InstrumentError("*OPC? did not report completion")

    def self_test(self) -> None:
        """*TST? — raises with the error queue on failure. Resets to default settings (p. 35)."""
        self._long_operation("*TST?", self._api.self_test)

    def calibrate(self) -> None:
        """*CAL? — auto calibration; raises with the error queue on failure."""
        self._long_operation("*CAL?", self._api.auto_calibrate)

    @property
    def instrument_status(self) -> InstrumentStatus:
        """INSR? — reading clears the register."""
        with self._lock:
            return self._api.get_instrument_status()

    @property
    def timebase(self) -> Timebase:
        with self._lock:
            return self._api.get_timebase()

    # ----- Internals used by the components -------------------------------------

    def _get(self, read: Callable[[], T]) -> T:
        with self._lock:
            return read()

    def _set(self, name: str, value: T, write: Callable[[T], object], read: Callable[[], T]) -> None:
        """Send, check the error queue, then read back if ``verify`` is on.

        ``write`` returns the value actually sent (rounded Decimal) or ``None``
        when the value is sent unchanged.
        """
        with self._lock:
            sent = write(value)
            expected = value if sent is None else sent
            self._raise_on_errors(name)
            if self._verify:
                actual = read()
                if actual != expected:
                    raise DG645VerificationError(name, expected, actual)

    def _command(self, name: str, send: Callable[[], None]) -> None:
        with self._lock:
            send()
            self._raise_on_errors(name)

    def _long_operation(self, name: str, run: Callable[[], ErrorCode]) -> None:
        with self._lock:
            result = run()
            errors = tuple(self._api.read_error_queue())
            if result is not ErrorCode.NO_ERROR or errors:
                raise DG645InstrumentError(f"{name} failed", (result, *errors))

    def _raise_on_errors(self, name: str) -> None:
        errors = self._api.read_error_queue()
        if errors:
            raise DG645InstrumentError(f"{name} failed", tuple(errors))

    def _require_advanced_triggering(self, setting: str) -> None:
        if self._api.get_advanced_triggering() is not State.ON:
            raise DG645ModeError(
                f"{setting} needs advanced triggering; set trigger.advanced = State.ON first (pp. 23–25)"
            )


class Trigger:
    """Trigger settings (pp. 22–25, 52–54). Access via ``ddg.trigger``."""

    def __init__(self, ddg: DigitalDelayGenerator):
        self._ddg = ddg
        self._api = ddg.api

    @property
    def source(self) -> TriggerSource:
        return self._ddg._get(self._api.get_trigger_source)

    @source.setter
    def source(self, value: TriggerSource) -> None:
        self._ddg._set("TSRC", value, self._api.set_trigger_source, self._api.get_trigger_source)

    @property
    def rate(self) -> Decimal:
        """Internal trigger rate [Hz]."""
        return self._ddg._get(self._api.get_trigger_rate)

    @rate.setter
    def rate(self, value: Decimal) -> None:
        self._ddg._set("TRAT", value, self._api.set_trigger_rate, self._api.get_trigger_rate)

    @property
    def level(self) -> Decimal:
        """External trigger threshold [V]."""
        return self._ddg._get(self._api.get_trigger_level)

    @level.setter
    def level(self, value: Decimal) -> None:
        self._ddg._set("TLVL", value, self._api.set_trigger_level, self._api.get_trigger_level)

    @property
    def inhibit(self) -> Inhibit:
        return self._ddg._get(self._api.get_inhibit)

    @inhibit.setter
    def inhibit(self, value: Inhibit) -> None:
        self._ddg._set("INHB", value, self._api.set_inhibit, self._api.get_inhibit)

    @property
    def advanced(self) -> State:
        """Advanced triggering; activates the stored holdoff and prescale values."""
        return self._ddg._get(self._api.get_advanced_triggering)

    @advanced.setter
    def advanced(self, value: State) -> None:
        self._ddg._set("ADVT", value, self._api.set_advanced_triggering, self._api.get_advanced_triggering)

    @property
    def holdoff(self) -> Decimal:
        """Minimum time between triggers [s]. Setting needs advanced triggering."""
        return self._ddg._get(self._api.get_holdoff)

    @holdoff.setter
    def holdoff(self, value: Decimal) -> None:
        with self._ddg._lock:
            self._ddg._require_advanced_triggering("Trigger holdoff")
            self._ddg._set("HOLD", value, self._api.set_holdoff, self._api.get_holdoff)

    @property
    def prescale(self) -> int:
        """Trigger prescale factor N. Setting needs advanced triggering."""
        return self._ddg._get(lambda: self._api.get_prescale_factor(Prescaler.TRIGGER))

    @prescale.setter
    def prescale(self, value: int) -> None:
        with self._ddg._lock:
            self._ddg._require_advanced_triggering("Trigger prescaling")
            self._ddg._set(
                "PRES",
                value,
                lambda v: self._api.set_prescale_factor(Prescaler.TRIGGER, v),
                lambda: self._api.get_prescale_factor(Prescaler.TRIGGER),
            )


class Burst:
    """Burst mode (pp. 26, 54–55). Access via ``ddg.burst``."""

    def __init__(self, ddg: DigitalDelayGenerator):
        self._ddg = ddg
        self._api = ddg.api

    @property
    def enabled(self) -> State:
        return self._ddg._get(self._api.get_burst_mode)

    @enabled.setter
    def enabled(self, value: State) -> None:
        self._ddg._set("BURM", value, self._api.set_burst_mode, self._api.get_burst_mode)

    @property
    def count(self) -> int:
        return self._ddg._get(self._api.get_burst_count)

    @count.setter
    def count(self, value: int) -> None:
        self._ddg._set("BURC", value, self._api.set_burst_count, self._api.get_burst_count)

    @property
    def delay(self) -> Decimal:
        """Delay from trigger to the first cycle [s], rounded to 5 ps."""
        return self._ddg._get(self._api.get_burst_delay)

    @delay.setter
    def delay(self, value: Decimal) -> None:
        self._ddg._set("BURD", value, self._api.set_burst_delay, self._api.get_burst_delay)

    @property
    def period(self) -> Decimal:
        """Time between cycles [s], rounded to 10 ns."""
        return self._ddg._get(self._api.get_burst_period)

    @period.setter
    def period(self, value: Decimal) -> None:
        self._ddg._set("BURP", value, self._api.set_burst_period, self._api.get_burst_period)

    @property
    def t0_mode(self) -> BurstT0Mode:
        return self._ddg._get(self._api.get_burst_t0_mode)

    @t0_mode.setter
    def t0_mode(self, value: BurstT0Mode) -> None:
        self._ddg._set("BURT", value, self._api.set_burst_t0_mode, self._api.get_burst_t0_mode)


class DelayChannel:
    """One of the delay channels A–H. Access via ``ddg.channels[Channel.A]``."""

    def __init__(self, ddg: DigitalDelayGenerator, channel: Channel):
        self._ddg = ddg
        self._api = ddg.api
        self.channel = channel

    @property
    def delay(self) -> DelaySetting:
        """Reference channel and offset [s]; the offset is rounded to 5 ps."""
        return self._ddg._get(lambda: self._api.get_delay(self.channel))

    @delay.setter
    def delay(self, value: DelaySetting) -> None:
        if not isinstance(value, DelaySetting):
            raise TypeError(f"delay must be a DelaySetting, got {value!r}")
        self._ddg._set(
            f"DLAY {self.channel.name}",
            value,
            lambda v: DelaySetting(v.reference, self._api.set_delay(self.channel, v.reference, v.offset)),
            lambda: self._api.get_delay(self.channel),
        )


class OutputControl:
    """One front-panel output (T0, AB, CD, EF, GH). Access via ``ddg.outputs[Output.AB]``."""

    def __init__(self, ddg: DigitalDelayGenerator, output: Output):
        self._ddg = ddg
        self._api = ddg.api
        self.output = output

    @property
    def amplitude(self) -> Decimal:
        """[V], 0.5–5.0, rounded to 0.01 V."""
        return self._ddg._get(lambda: self._api.get_amplitude(self.output))

    @amplitude.setter
    def amplitude(self, value: Decimal) -> None:
        self._ddg._set(
            f"LAMP {self.output.name}",
            value,
            lambda v: self._api.set_amplitude(self.output, v),
            lambda: self._api.get_amplitude(self.output),
        )

    @property
    def offset(self) -> Decimal:
        """[V], ±2.0, rounded to 0.01 V."""
        return self._ddg._get(lambda: self._api.get_offset(self.output))

    @offset.setter
    def offset(self, value: Decimal) -> None:
        self._ddg._set(
            f"LOFF {self.output.name}",
            value,
            lambda v: self._api.set_offset(self.output, v),
            lambda: self._api.get_offset(self.output),
        )

    @property
    def polarity(self) -> Polarity:
        return self._ddg._get(lambda: self._api.get_polarity(self.output))

    @polarity.setter
    def polarity(self, value: Polarity) -> None:
        self._ddg._set(
            f"LPOL {self.output.name}",
            value,
            lambda v: self._api.set_polarity(self.output, v),
            lambda: self._api.get_polarity(self.output),
        )

    @property
    def prescale(self) -> int:
        """Output prescale factor M (AB–GH). Setting needs advanced triggering."""
        p = self._prescaler()
        return self._ddg._get(lambda: self._api.get_prescale_factor(p))

    @prescale.setter
    def prescale(self, value: int) -> None:
        p = self._prescaler()
        with self._ddg._lock:
            self._ddg._require_advanced_triggering(f"Prescaling of {self.output.name}")
            self._ddg._set(
                f"PRES {p.name}",
                value,
                lambda v: self._api.set_prescale_factor(p, v),
                lambda: self._api.get_prescale_factor(p),
            )

    @property
    def phase(self) -> int:
        """Prescaler phase 0..M-1 (AB–GH). Setting needs advanced triggering."""
        p = self._prescaler()
        return self._ddg._get(lambda: self._api.get_prescale_phase(p))

    @phase.setter
    def phase(self, value: int) -> None:
        p = self._prescaler()
        with self._ddg._lock:
            self._ddg._require_advanced_triggering(f"Prescaler phase of {self.output.name}")
            self._ddg._set(
                f"PHAS {p.name}",
                value,
                lambda v: self._api.set_prescale_phase(p, v),
                lambda: self._api.get_prescale_phase(p),
            )

    def _prescaler(self) -> Prescaler:
        if self.output is Output.T0:
            raise DG645ModeError("T0 has no output prescaler; use trigger.prescale")
        return Prescaler[self.output.name]
