"""Central command layer: one method per DG645 remote command, all 70 of them.

Conventions
-----------
* Every coded setting is an enum from :mod:`dg645.enums`; plain ints are rejected.
* Every physical quantity (seconds, hertz, volts) is a :class:`decimal.Decimal`;
  floats are rejected. Values are sent in fixed-point notation, so nothing is lost.
* Values with a documented resolution are rounded (half up) to that grid, e.g.
  delays to 5 ps. Setters taking a Decimal return the value actually sent.
  Range limits are checked after rounding and raise ``ValueError``.
* Counts, prescale factors, phases, save slots and GPIB addresses are ``int``.
* Arguments are validated against the limits stated in the manual before anything
  is sent. Each limit below cites its page.
* This layer does not read the error queue after a set command. Use
  :meth:`DG645Api.get_last_error` / :meth:`DG645Api.read_error_queue` for that.

* Queries use the transport's timeout (1 s by default). ``*CAL?`` and ``*TST?``
  only reply once the routine has finished, so they get
  :data:`LONG_OPERATION_TIMEOUT_S`; ``*OPC?`` takes an optional timeout.

Wire format follows the manual's examples: set ``"DLAY 2,0,0.000010000000"``,
query ``"DLAY?3"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from ipaddress import IPv4Address
from typing import TypeVar

from .enums import (
    BaudRate,
    BurstT0Mode,
    Channel,
    Display,
    ErrorCode,
    EthernetPhyItem,
    EventStatus,
    Inhibit,
    InstrumentStatus,
    Interface,
    InterfaceConfig,
    LinkSpeed,
    Output,
    Polarity,
    PowerOnStatusClear,
    Prescaler,
    State,
    StatusByte,
    StepDirection,
    Timebase,
    TriggerSource,
)
from .errors import DG645ResponseError
from .transport import Transport

E = TypeVar("E", bound=Enum)

# --- Limits from the manual ---------------------------------------------------

DELAY_MAX = Decimal("1999.999999999995")       # p. 27
DELAY_RESOLUTION = Decimal("5E-12")             # p. 27, specs p. vii
TRIGGER_RATE_MIN = Decimal("0.0001")            # 100 µHz, p. 22, specs p. vii
TRIGGER_RATE_MAX = Decimal("10000000")          # 10 MHz
TRIGGER_RATE_RESOLUTION = Decimal("0.000001")   # 1 µHz
TRIGGER_LEVEL_MAX = Decimal("3.5")              # ±3.5 V, p. 22, specs p. vii
TRIGGER_PRESCALE_MAX = 2**30 - 1                # p. 25
OUTPUT_PRESCALE_MAX = 2**16 - 1                 # p. 25; phase 0 .. M-1
BURST_COUNT_MAX = 2**32 - 1                     # p. 26, specs p. viii
BURST_DELAY_MAX = Decimal("2000")               # specs p. viii
BURST_PERIOD_MIN = Decimal("100E-9")            # p. 55
BURST_PERIOD_MAX = Decimal("2000") - Decimal("10E-9")  # p. 55 (specs p. viii says 42.9 s)
BURST_PERIOD_RESOLUTION = Decimal("10E-9")      # p. 55
AMPLITUDE_MIN = Decimal("0.5")                  # p. 28
AMPLITUDE_MAX = Decimal("5.0")
OFFSET_MAX = Decimal("2.0")                     # ±2.0 V, p. 28
LEVEL_RESOLUTION = Decimal("0.01")              # p. 28
RECALL_SLOTS = range(0, 10)                     # p. 49, 0 = factory defaults
SAVE_SLOTS = range(1, 10)                       # p. 49
GPIB_ADDRESSES = range(0, 31)                   # p. 58
PARAMETER_MAX_BYTES = 25                        # p. 44
# *CAL? / *TST? durations are not in the manual; srsinst.dg645's tests allow 300 s for *CAL?.
LONG_OPERATION_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class Identification:
    manufacturer: str
    model: str
    serial_number: str
    firmware_version: str


@dataclass(frozen=True)
class DelaySetting:
    """A channel's delay: ``reference`` + ``offset`` seconds."""

    reference: Channel
    offset: Decimal


@dataclass(frozen=True)
class DisplaySetting:
    display: Display
    channel: Channel


# --- Validation and encoding ----------------------------------------------------

def _enum(value: object, cls: type[E], name: str, allowed: tuple[E, ...] | None = None) -> E:
    if not isinstance(value, cls):
        raise TypeError(f"{name} must be a {cls.__name__}, got {value!r}")
    if allowed is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {[a.name for a in allowed]}, got {value.name}")
    return value


def _int(value: object, name: str, lo: int, hi: int) -> int:
    if not isinstance(value, int) or isinstance(value, (bool, Enum)):
        raise TypeError(f"{name} must be an int, got {value!r}")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in [{lo}, {hi}], got {value}")
    return value


def _decimal(
    value: object,
    name: str,
    lo: Decimal | None = None,
    hi: Decimal | None = None,
    resolution: Decimal | None = None,
) -> Decimal:
    """Validate a Decimal, round it to ``resolution`` and check the range."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__} {value!r}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    if resolution is not None:
        steps = (value / resolution).to_integral_value(rounding=ROUND_HALF_UP)
        value = (steps * resolution).quantize(resolution)  # fixed number of decimals per grid
        if value == 0:
            value = value.copy_abs()  # no "-0.000…" on the wire
    if lo is not None and value < lo:
        raise ValueError(f"{name} must be >= {lo}, got {value}")
    if hi is not None and value > hi:
        raise ValueError(f"{name} must be <= {hi}, got {value}")
    return value


def _positive_step(value: object, name: str, resolution: Decimal | None = None) -> Decimal:
    value = _decimal(value, name, resolution=resolution)
    if value <= 0:
        raise ValueError(f"{name} must be > 0 after rounding to {resolution}, got {value}")
    return value


def _wire(value: Decimal) -> str:
    """Fixed-point representation as sent to the instrument."""
    text = format(value, "f")
    if len(text) > PARAMETER_MAX_BYTES:
        raise ValueError(f"{text} needs {len(text)} characters, the instrument accepts {PARAMETER_MAX_BYTES}")
    return text


def _parse_int(reply: str, command: str) -> int:
    try:
        return int(reply.strip())
    except ValueError:
        raise DG645ResponseError(f"{command}: expected an integer, got {reply!r}") from None


def _parse_decimal(reply: str, command: str) -> Decimal:
    try:
        value = Decimal(reply.strip())
    except ArithmeticError:
        raise DG645ResponseError(f"{command}: expected a number, got {reply!r}") from None
    if not value.is_finite():
        raise DG645ResponseError(f"{command}: expected a finite number, got {reply!r}")
    return value


def _parse_enum(reply: str, cls: type[E], command: str) -> E:
    code = _parse_int(reply, command)
    try:
        return cls(code)
    except ValueError:
        raise DG645ResponseError(f"{command}: {code} is not a valid {cls.__name__}") from None


def _parse_fields(reply: str, count: int, command: str) -> list[str]:
    fields = reply.strip().split(",")
    if len(fields) != count:
        raise DG645ResponseError(f"{command}: expected {count} fields, got {reply!r}")
    return fields


_IFCF_STATE_ITEMS = frozenset({
    InterfaceConfig.RS232_ENABLE, InterfaceConfig.GPIB_ENABLE, InterfaceConfig.TCPIP_ENABLE,
    InterfaceConfig.DHCP_ENABLE, InterfaceConfig.AUTO_IP_ENABLE, InterfaceConfig.STATIC_IP_ENABLE,
    InterfaceConfig.BARE_SOCKET_ENABLE, InterfaceConfig.TELNET_ENABLE, InterfaceConfig.VXI11_ENABLE,
})
_IFCF_ADDRESS_ITEMS = frozenset({
    InterfaceConfig.STATIC_IP_ADDRESS, InterfaceConfig.SUBNET_MASK, InterfaceConfig.DEFAULT_GATEWAY,
})
_PHASE_PRESCALERS = (Prescaler.AB, Prescaler.CD, Prescaler.EF, Prescaler.GH)
_LINKABLE_TARGETS = tuple(c for c in Channel if c not in (Channel.T0, Channel.T1))
_LINK_REFERENCES = tuple(c for c in Channel if c is not Channel.T1)
InterfaceConfigValue = State | BaudRate | int | IPv4Address


def _prescale_max(prescaler: Prescaler) -> int:
    return TRIGGER_PRESCALE_MAX if prescaler is Prescaler.TRIGGER else OUTPUT_PRESCALE_MAX


# --- API ------------------------------------------------------------------------

class DG645Api:
    """One method per remote command. Method docstrings name the command and manual page."""

    def __init__(self, transport: Transport):
        self._transport = transport

    def _write(self, command: str) -> None:
        self._transport.write(command)

    def _query(self, command: str, timeout_s: float | None = None) -> str:
        return self._transport.query(command, timeout_s)

    # ===== IEEE-488.2 common commands (pp. 48–50) ==============================

    def auto_calibrate(self, timeout_s: float = LONG_OPERATION_TIMEOUT_S) -> ErrorCode:
        """*CAL? — run auto calibration. NO_ERROR or FAILED_AUTO_CALIBRATION. p. 48"""
        return _parse_enum(self._query("*CAL?", timeout_s), ErrorCode, "*CAL?")

    def clear_status(self) -> None:
        """*CLS — clear ESR, INSR and the error queue. p. 48"""
        self._write("*CLS")

    def get_standard_event_status_enable(self) -> EventStatus:
        """*ESE? p. 48"""
        return EventStatus(_parse_int(self._query("*ESE?"), "*ESE?"))

    def set_standard_event_status_enable(self, mask: EventStatus) -> None:
        """*ESE i p. 48"""
        self._write(f"*ESE {_enum(mask, EventStatus, 'mask').value}")

    def get_standard_event_status(self) -> EventStatus:
        """*ESR? — read and clear the standard event status register. p. 48"""
        return EventStatus(_parse_int(self._query("*ESR?"), "*ESR?"))

    def identify(self) -> Identification:
        """*IDN? p. 48"""
        reply = self._query("*IDN?")
        return Identification(*(f.strip() for f in _parse_fields(reply, 4, "*IDN?")))

    def set_operation_complete_flag(self) -> None:
        """*OPC — set OPC in ESR once all prior commands have completed. p. 48"""
        self._write("*OPC")

    def query_operation_complete(self, timeout_s: float | None = None) -> bool:
        """*OPC? — returns once all prior commands have completed. p. 48"""
        return _parse_int(self._query("*OPC?", timeout_s), "*OPC?") == 1

    def get_power_on_status_clear(self) -> PowerOnStatusClear:
        """*PSC? p. 49"""
        return _parse_enum(self._query("*PSC?"), PowerOnStatusClear, "*PSC?")

    def set_power_on_status_clear(self, value: PowerOnStatusClear) -> None:
        """*PSC i p. 49"""
        self._write(f"*PSC {_enum(value, PowerOnStatusClear, 'value').value}")

    def recall_settings(self, slot: int) -> None:
        """*RCL i — slot 0 = factory defaults, 1–9 = user. p. 49"""
        self._write(f"*RCL {_int(slot, 'slot', RECALL_SLOTS.start, RECALL_SLOTS.stop - 1)}")

    def reset(self) -> None:
        """*RST — factory defaults, same as *RCL 0. p. 49"""
        self._write("*RST")

    def save_settings(self, slot: int) -> None:
        """*SAV i — slot 1–9. p. 49"""
        self._write(f"*SAV {_int(slot, 'slot', SAVE_SLOTS.start, SAVE_SLOTS.stop - 1)}")

    def get_service_request_enable(self) -> StatusByte:
        """*SRE? p. 49"""
        return StatusByte(_parse_int(self._query("*SRE?"), "*SRE?"))

    def set_service_request_enable(self, mask: StatusByte) -> None:
        """*SRE i p. 49"""
        self._write(f"*SRE {_enum(mask, StatusByte, 'mask').value}")

    def get_status_byte(self) -> StatusByte:
        """*STB? p. 49"""
        return StatusByte(_parse_int(self._query("*STB?"), "*STB?"))

    def trigger(self) -> None:
        """*TRG — fire a single shot, or arm an external single shot. p. 50"""
        self._write("*TRG")

    def self_test(self, timeout_s: float = LONG_OPERATION_TIMEOUT_S) -> ErrorCode:
        """*TST? — NO_ERROR or FAILED_SELF_TEST; resets to default settings (p. 35). p. 50"""
        return _parse_enum(self._query("*TST?", timeout_s), ErrorCode, "*TST?")

    def wait(self) -> None:
        """*WAI — process no further commands until prior ones have completed. p. 50"""
        self._write("*WAI")

    # ===== Status and display (pp. 50–52) ======================================

    def get_display(self) -> DisplaySetting:
        """DISP? p. 50"""
        display, channel = _parse_fields(self._query("DISP?"), 2, "DISP?")
        return DisplaySetting(_parse_enum(display, Display, "DISP?"), _parse_enum(channel, Channel, "DISP?"))

    def set_display(self, display: Display, channel: Channel) -> None:
        """DISP i,c p. 50"""
        self._write(f"DISP {_enum(display, Display, 'display').value},{_enum(channel, Channel, 'channel').value}")

    def get_instrument_status_enable(self) -> InstrumentStatus:
        """INSE? p. 51"""
        return InstrumentStatus(_parse_int(self._query("INSE?"), "INSE?"))

    def set_instrument_status_enable(self, mask: InstrumentStatus) -> None:
        """INSE i p. 51"""
        self._write(f"INSE {_enum(mask, InstrumentStatus, 'mask').value}")

    def get_instrument_status(self) -> InstrumentStatus:
        """INSR? — read and clear the instrument status register. p. 51"""
        return InstrumentStatus(_parse_int(self._query("INSR?"), "INSR?"))

    def get_last_error(self) -> ErrorCode:
        """LERR? — pop one error from the queue (20 entries). p. 51"""
        return _parse_enum(self._query("LERR?"), ErrorCode, "LERR?")

    def read_error_queue(self) -> list[ErrorCode]:
        """Pop LERR? until NO_ERROR. Not a separate command; at most 20 reads."""
        errors: list[ErrorCode] = []
        for _ in range(20):
            code = self.get_last_error()
            if code is ErrorCode.NO_ERROR:
                break
            errors.append(code)
        return errors

    def get_display_enabled(self) -> State:
        """SHDP? p. 51"""
        return _parse_enum(self._query("SHDP?"), State, "SHDP?")

    def set_display_enabled(self, state: State) -> None:
        """SHDP i p. 51"""
        self._write(f"SHDP {_enum(state, State, 'state').value}")

    def get_timebase(self) -> Timebase:
        """TIMB? p. 51"""
        return _parse_enum(self._query("TIMB?"), Timebase, "TIMB?")

    # ===== Trigger (pp. 52–54) =================================================

    def get_advanced_triggering(self) -> State:
        """ADVT? p. 52"""
        return _parse_enum(self._query("ADVT?"), State, "ADVT?")

    def set_advanced_triggering(self, state: State) -> None:
        """ADVT i — required for holdoff and prescaling (pp. 23–25). p. 52"""
        self._write(f"ADVT {_enum(state, State, 'state').value}")

    def get_holdoff(self) -> Decimal:
        """HOLD? [s] p. 52"""
        return _parse_decimal(self._query("HOLD?"), "HOLD?")

    def set_holdoff(self, seconds: Decimal) -> Decimal:
        """HOLD t [s] — resolution and upper limit not documented; the instrument checks them. p. 52"""
        v = _decimal(seconds, "seconds", lo=Decimal(0))
        self._write(f"HOLD {_wire(v)}")
        return v

    def get_inhibit(self) -> Inhibit:
        """INHB? p. 52"""
        return _parse_enum(self._query("INHB?"), Inhibit, "INHB?")

    def set_inhibit(self, inhibit: Inhibit) -> None:
        """INHB i p. 52"""
        self._write(f"INHB {_enum(inhibit, Inhibit, 'inhibit').value}")

    def get_prescale_phase(self, prescaler: Prescaler) -> int:
        """PHAS?i — AB–GH only. p. 52"""
        p = _enum(prescaler, Prescaler, "prescaler", _PHASE_PRESCALERS)
        return _parse_int(self._query(f"PHAS?{p.value}"), "PHAS?")

    def set_prescale_phase(self, prescaler: Prescaler, phase: int) -> None:
        """PHAS i,j — phase 0 .. M-1 (p. 25); the instrument checks against M. p. 52"""
        p = _enum(prescaler, Prescaler, "prescaler", _PHASE_PRESCALERS)
        self._write(f"PHAS {p.value},{_int(phase, 'phase', 0, OUTPUT_PRESCALE_MAX - 1)}")

    def get_prescale_factor(self, prescaler: Prescaler) -> int:
        """PRES?i p. 53"""
        p = _enum(prescaler, Prescaler, "prescaler")
        return _parse_int(self._query(f"PRES?{p.value}"), "PRES?")

    def set_prescale_factor(self, prescaler: Prescaler, factor: int) -> None:
        """PRES i,j — trigger 1..2^30-1, outputs 1..2^16-1 (p. 25). p. 53"""
        p = _enum(prescaler, Prescaler, "prescaler")
        self._write(f"PRES {p.value},{_int(factor, 'factor', 1, _prescale_max(p))}")

    def step_holdoff(self, direction: StepDirection) -> None:
        """SPHD i p. 53"""
        self._write(f"SPHD {_enum(direction, StepDirection, 'direction').value}")

    def step_prescale_phase(self, prescaler: Prescaler, direction: StepDirection) -> None:
        """SPPH i,j — AB–GH only. p. 53"""
        p = _enum(prescaler, Prescaler, "prescaler", _PHASE_PRESCALERS)
        self._write(f"SPPH {p.value},{_enum(direction, StepDirection, 'direction').value}")

    def step_prescale_factor(self, prescaler: Prescaler, direction: StepDirection) -> None:
        """SPPS i,j p. 53"""
        p = _enum(prescaler, Prescaler, "prescaler")
        self._write(f"SPPS {p.value},{_enum(direction, StepDirection, 'direction').value}")

    def step_trigger_level(self, direction: StepDirection) -> None:
        """SPTL i p. 53"""
        self._write(f"SPTL {_enum(direction, StepDirection, 'direction').value}")

    def step_trigger_rate(self, direction: StepDirection) -> None:
        """SPTR i p. 53"""
        self._write(f"SPTR {_enum(direction, StepDirection, 'direction').value}")

    def get_holdoff_step_size(self) -> Decimal:
        """SSHD? [s] p. 54"""
        return _parse_decimal(self._query("SSHD?"), "SSHD?")

    def set_holdoff_step_size(self, seconds: Decimal) -> Decimal:
        """SSHD t [s] p. 54"""
        v = _positive_step(seconds, "seconds")
        self._write(f"SSHD {_wire(v)}")
        return v

    def get_prescale_phase_step_size(self, prescaler: Prescaler) -> int:
        """SSPH?i — AB–GH only. p. 54"""
        p = _enum(prescaler, Prescaler, "prescaler", _PHASE_PRESCALERS)
        return _parse_int(self._query(f"SSPH?{p.value}"), "SSPH?")

    def set_prescale_phase_step_size(self, prescaler: Prescaler, step: int) -> None:
        """SSPH i,j p. 54"""
        p = _enum(prescaler, Prescaler, "prescaler", _PHASE_PRESCALERS)
        self._write(f"SSPH {p.value},{_int(step, 'step', 1, OUTPUT_PRESCALE_MAX - 1)}")

    def get_prescale_factor_step_size(self, prescaler: Prescaler) -> int:
        """SSPS?i p. 54"""
        p = _enum(prescaler, Prescaler, "prescaler")
        return _parse_int(self._query(f"SSPS?{p.value}"), "SSPS?")

    def set_prescale_factor_step_size(self, prescaler: Prescaler, step: int) -> None:
        """SSPS i,j p. 54"""
        p = _enum(prescaler, Prescaler, "prescaler")
        self._write(f"SSPS {p.value},{_int(step, 'step', 1, _prescale_max(p))}")

    def get_trigger_level_step_size(self) -> Decimal:
        """SSTL? [V] p. 54"""
        return _parse_decimal(self._query("SSTL?"), "SSTL?")

    def set_trigger_level_step_size(self, volts: Decimal) -> Decimal:
        """SSTL v [V] p. 54"""
        v = _positive_step(volts, "volts")
        self._write(f"SSTL {_wire(v)}")
        return v

    def get_trigger_rate_step_size(self) -> Decimal:
        """SSTR? [Hz] p. 54"""
        return _parse_decimal(self._query("SSTR?"), "SSTR?")

    def set_trigger_rate_step_size(self, hertz: Decimal) -> Decimal:
        """SSTR f [Hz] — rounded to 1 µHz. p. 54"""
        v = _positive_step(hertz, "hertz", TRIGGER_RATE_RESOLUTION)
        self._write(f"SSTR {_wire(v)}")
        return v

    def get_trigger_level(self) -> Decimal:
        """TLVL? [V] p. 54"""
        return _parse_decimal(self._query("TLVL?"), "TLVL?")

    def set_trigger_level(self, volts: Decimal) -> Decimal:
        """TLVL v [V] — ±3.5 V; resolution not documented. p. 54"""
        v = _decimal(volts, "volts", -TRIGGER_LEVEL_MAX, TRIGGER_LEVEL_MAX)
        self._write(f"TLVL {_wire(v)}")
        return v

    def get_trigger_rate(self) -> Decimal:
        """TRAT? [Hz] p. 54"""
        return _parse_decimal(self._query("TRAT?"), "TRAT?")

    def set_trigger_rate(self, hertz: Decimal) -> Decimal:
        """TRAT f [Hz] — 100 µHz .. 10 MHz, rounded to 1 µHz. p. 54"""
        v = _decimal(hertz, "hertz", TRIGGER_RATE_MIN, TRIGGER_RATE_MAX, TRIGGER_RATE_RESOLUTION)
        self._write(f"TRAT {_wire(v)}")
        return v

    def get_trigger_source(self) -> TriggerSource:
        """TSRC? p. 54"""
        return _parse_enum(self._query("TSRC?"), TriggerSource, "TSRC?")

    def set_trigger_source(self, source: TriggerSource) -> None:
        """TSRC i p. 54"""
        self._write(f"TSRC {_enum(source, TriggerSource, 'source').value}")

    # ===== Burst (pp. 54–55) ===================================================

    def get_burst_count(self) -> int:
        """BURC? p. 54"""
        return _parse_int(self._query("BURC?"), "BURC?")

    def set_burst_count(self, count: int) -> None:
        """BURC i — 1 .. 2^32-1 (p. 26). p. 54"""
        self._write(f"BURC {_int(count, 'count', 1, BURST_COUNT_MAX)}")

    def get_burst_delay(self) -> Decimal:
        """BURD? [s] p. 55"""
        return _parse_decimal(self._query("BURD?"), "BURD?")

    def set_burst_delay(self, seconds: Decimal) -> Decimal:
        """BURD t [s] — 0 .. 2000 s, rounded to 5 ps (p. 26). p. 55"""
        v = _decimal(seconds, "seconds", Decimal(0), BURST_DELAY_MAX, DELAY_RESOLUTION)
        self._write(f"BURD {_wire(v)}")
        return v

    def get_burst_mode(self) -> State:
        """BURM? p. 55"""
        return _parse_enum(self._query("BURM?"), State, "BURM?")

    def set_burst_mode(self, state: State) -> None:
        """BURM i p. 55"""
        self._write(f"BURM {_enum(state, State, 'state').value}")

    def get_burst_period(self) -> Decimal:
        """BURP? [s] p. 55"""
        return _parse_decimal(self._query("BURP?"), "BURP?")

    def set_burst_period(self, seconds: Decimal) -> Decimal:
        """BURP t [s] — 100 ns .. 2000 s - 10 ns, rounded to 10 ns. p. 55"""
        v = _decimal(seconds, "seconds", BURST_PERIOD_MIN, BURST_PERIOD_MAX, BURST_PERIOD_RESOLUTION)
        self._write(f"BURP {_wire(v)}")
        return v

    def get_burst_t0_mode(self) -> BurstT0Mode:
        """BURT? p. 55"""
        return _parse_enum(self._query("BURT?"), BurstT0Mode, "BURT?")

    def set_burst_t0_mode(self, mode: BurstT0Mode) -> None:
        """BURT i p. 55"""
        self._write(f"BURT {_enum(mode, BurstT0Mode, 'mode').value}")

    def step_burst_count(self, direction: StepDirection) -> None:
        """SPBC i p. 55"""
        self._write(f"SPBC {_enum(direction, StepDirection, 'direction').value}")

    def step_burst_delay(self, direction: StepDirection) -> None:
        """SPBD i p. 55"""
        self._write(f"SPBD {_enum(direction, StepDirection, 'direction').value}")

    def step_burst_period(self, direction: StepDirection) -> None:
        """SPBP i p. 55"""
        self._write(f"SPBP {_enum(direction, StepDirection, 'direction').value}")

    def get_burst_count_step_size(self) -> int:
        """SSBC? p. 55"""
        return _parse_int(self._query("SSBC?"), "SSBC?")

    def set_burst_count_step_size(self, step: int) -> None:
        """SSBC i p. 55"""
        self._write(f"SSBC {_int(step, 'step', 1, BURST_COUNT_MAX)}")

    def get_burst_delay_step_size(self) -> Decimal:
        """SSBD? [s] p. 55"""
        return _parse_decimal(self._query("SSBD?"), "SSBD?")

    def set_burst_delay_step_size(self, seconds: Decimal) -> Decimal:
        """SSBD t [s] — rounded to 5 ps. p. 55"""
        v = _positive_step(seconds, "seconds", DELAY_RESOLUTION)
        self._write(f"SSBD {_wire(v)}")
        return v

    def get_burst_period_step_size(self) -> Decimal:
        """SSBP? [s] p. 55"""
        return _parse_decimal(self._query("SSBP?"), "SSBP?")

    def set_burst_period_step_size(self, seconds: Decimal) -> Decimal:
        """SSBP t [s] — rounded to 10 ns. p. 55"""
        v = _positive_step(seconds, "seconds", BURST_PERIOD_RESOLUTION)
        self._write(f"SSBP {_wire(v)}")
        return v

    # ===== Delay and output (pp. 56–57) ========================================

    def get_delay(self, channel: Channel) -> DelaySetting:
        """DLAY?c — e.g. reply '2,+0.001000000000'. p. 56"""
        c = _enum(channel, Channel, "channel")
        reference, offset = _parse_fields(self._query(f"DLAY?{c.value}"), 2, "DLAY?")
        return DelaySetting(_parse_enum(reference, Channel, "DLAY?"), _parse_decimal(offset, "DLAY?"))

    def set_delay(self, channel: Channel, reference: Channel, seconds: Decimal) -> Decimal:
        """DLAY c,d,t — channel = reference + seconds. p. 56

        T0 and T1 are predefined and cannot be set (p. 27). A relative offset may be
        negative (Table 12, p. 27); the resulting absolute delay must lie in
        0 .. 1999.999999999995 s, which the instrument checks (error ILLEGAL_DELAY).
        ``seconds`` is rounded to 5 ps.
        """
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        d = _enum(reference, Channel, "reference", _LINK_REFERENCES)
        if c is d:
            raise ValueError("channel cannot be its own reference")
        v = _decimal(seconds, "seconds", -DELAY_MAX, DELAY_MAX, DELAY_RESOLUTION)
        self._write(f"DLAY {c.value},{d.value},{_wire(v)}")
        return v

    def get_amplitude(self, output: Output) -> Decimal:
        """LAMP?b [V] p. 56"""
        b = _enum(output, Output, "output")
        return _parse_decimal(self._query(f"LAMP?{b.value}"), "LAMP?")

    def set_amplitude(self, output: Output, volts: Decimal) -> Decimal:
        """LAMP b,v [V] — 0.5 .. 5.0 V, rounded to 0.01 V; |level| <= 6 V checked by the instrument. p. 56"""
        b = _enum(output, Output, "output")
        v = _decimal(volts, "volts", AMPLITUDE_MIN, AMPLITUDE_MAX, LEVEL_RESOLUTION)
        self._write(f"LAMP {b.value},{_wire(v)}")
        return v

    def get_link(self, channel: Channel) -> Channel:
        """LINK?c p. 56"""
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        return _parse_enum(self._query(f"LINK?{c.value}"), Channel, "LINK?")

    def set_link(self, channel: Channel, reference: Channel) -> None:
        """LINK c,d — c not T0, neither T1; circular links rejected by the instrument. p. 56"""
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        d = _enum(reference, Channel, "reference", _LINK_REFERENCES)
        if c is d:
            raise ValueError("channel cannot be linked to itself")
        self._write(f"LINK {c.value},{d.value}")

    def get_offset(self, output: Output) -> Decimal:
        """LOFF?b [V] p. 57"""
        b = _enum(output, Output, "output")
        return _parse_decimal(self._query(f"LOFF?{b.value}"), "LOFF?")

    def set_offset(self, output: Output, volts: Decimal) -> Decimal:
        """LOFF b,v [V] — ±2.0 V, rounded to 0.01 V. p. 57"""
        b = _enum(output, Output, "output")
        v = _decimal(volts, "volts", -OFFSET_MAX, OFFSET_MAX, LEVEL_RESOLUTION)
        self._write(f"LOFF {b.value},{_wire(v)}")
        return v

    def get_polarity(self, output: Output) -> Polarity:
        """LPOL?b p. 57"""
        b = _enum(output, Output, "output")
        return _parse_enum(self._query(f"LPOL?{b.value}"), Polarity, "LPOL?")

    def set_polarity(self, output: Output, polarity: Polarity) -> None:
        """LPOL b,i p. 57"""
        b = _enum(output, Output, "output")
        self._write(f"LPOL {b.value},{_enum(polarity, Polarity, 'polarity').value}")

    def step_delay(self, channel: Channel, direction: StepDirection) -> None:
        """SPDL c,i p. 57"""
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        self._write(f"SPDL {c.value},{_enum(direction, StepDirection, 'direction').value}")

    def step_amplitude(self, output: Output, direction: StepDirection) -> None:
        """SPLA b,i p. 57"""
        b = _enum(output, Output, "output")
        self._write(f"SPLA {b.value},{_enum(direction, StepDirection, 'direction').value}")

    def step_offset(self, output: Output, direction: StepDirection) -> None:
        """SPLO b,i p. 57"""
        b = _enum(output, Output, "output")
        self._write(f"SPLO {b.value},{_enum(direction, StepDirection, 'direction').value}")

    def get_delay_step_size(self, channel: Channel) -> Decimal:
        """SSDL?c [s] p. 57"""
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        return _parse_decimal(self._query(f"SSDL?{c.value}"), "SSDL?")

    def set_delay_step_size(self, channel: Channel, seconds: Decimal) -> Decimal:
        """SSDL c,t [s] (manual writes 'f') — rounded to 5 ps. p. 57"""
        c = _enum(channel, Channel, "channel", _LINKABLE_TARGETS)
        v = _positive_step(seconds, "seconds", DELAY_RESOLUTION)
        self._write(f"SSDL {c.value},{_wire(v)}")
        return v

    def get_amplitude_step_size(self, output: Output) -> Decimal:
        """SSLA?b [V] p. 57"""
        b = _enum(output, Output, "output")
        return _parse_decimal(self._query(f"SSLA?{b.value}"), "SSLA?")

    def set_amplitude_step_size(self, output: Output, volts: Decimal) -> Decimal:
        """SSLA b,v [V] — rounded to 0.01 V. p. 57"""
        b = _enum(output, Output, "output")
        v = _positive_step(volts, "volts", LEVEL_RESOLUTION)
        self._write(f"SSLA {b.value},{_wire(v)}")
        return v

    def get_offset_step_size(self, output: Output) -> Decimal:
        """SSLO?b [V] p. 57"""
        b = _enum(output, Output, "output")
        return _parse_decimal(self._query(f"SSLO?{b.value}"), "SSLO?")

    def set_offset_step_size(self, output: Output, volts: Decimal) -> Decimal:
        """SSLO b,v [V] — rounded to 0.01 V. p. 57"""
        b = _enum(output, Output, "output")
        v = _positive_step(volts, "volts", LEVEL_RESOLUTION)
        self._write(f"SSLO {b.value},{_wire(v)}")
        return v

    # ===== Interface (pp. 57–59) ===============================================

    def get_mac_address(self) -> str:
        """EMAC? — returned as sent by the instrument. p. 57"""
        return self._query("EMAC?").strip()

    def get_ethernet_auto_negotiation(self) -> State:
        """EPHY?0 p. 57"""
        return _parse_enum(self._query(f"EPHY?{EthernetPhyItem.AUTO_NEGOTIATION.value}"), State, "EPHY?")

    def set_ethernet_auto_negotiation(self, state: State) -> None:
        """EPHY 0,j p. 57"""
        self._write(f"EPHY {EthernetPhyItem.AUTO_NEGOTIATION.value},{_enum(state, State, 'state').value}")

    def get_ethernet_link_speed(self) -> LinkSpeed:
        """EPHY?1 p. 57"""
        return _parse_enum(self._query(f"EPHY?{EthernetPhyItem.LINK_SPEED.value}"), LinkSpeed, "EPHY?")

    def set_ethernet_link_speed(self, speed: LinkSpeed) -> None:
        """EPHY 1,j — ignored while auto-negotiation is on. p. 57"""
        self._write(f"EPHY {EthernetPhyItem.LINK_SPEED.value},{_enum(speed, LinkSpeed, 'speed').value}")

    def get_interface_config(self, item: InterfaceConfig) -> InterfaceConfigValue:
        """IFCF?i — State, BaudRate, int (GPIB address) or IPv4Address depending on item. p. 58"""
        i = _enum(item, InterfaceConfig, "item")
        reply = self._query(f"IFCF?{i.value}")
        if i in _IFCF_STATE_ITEMS:
            return _parse_enum(reply, State, "IFCF?")
        if i is InterfaceConfig.RS232_BAUD_RATE:
            return _parse_enum(reply, BaudRate, "IFCF?")
        if i is InterfaceConfig.GPIB_ADDRESS:
            return _parse_int(reply, "IFCF?")
        try:
            return IPv4Address(reply.strip())
        except ValueError:
            raise DG645ResponseError(f"IFCF?: expected an IPv4 address, got {reply!r}") from None

    def set_interface_config(self, item: InterfaceConfig, value: InterfaceConfigValue) -> None:
        """IFCF i,j — takes effect after IFRS or a power cycle. p. 58

        Value type per item: enable items -> State, RS232_BAUD_RATE -> BaudRate,
        GPIB_ADDRESS -> int 0..30, address items -> IPv4Address.
        """
        i = _enum(item, InterfaceConfig, "item")
        if i in _IFCF_STATE_ITEMS:
            text = str(_enum(value, State, "value").value)
        elif i is InterfaceConfig.RS232_BAUD_RATE:
            text = str(_enum(value, BaudRate, "value").value)
        elif i is InterfaceConfig.GPIB_ADDRESS:
            text = str(_int(value, "value", GPIB_ADDRESSES.start, GPIB_ADDRESSES.stop - 1))
        else:
            if not isinstance(value, IPv4Address):
                raise TypeError(f"value must be an IPv4Address for {i.name}, got {value!r}")
            text = str(value)
        self._write(f"IFCF {i.value},{text}")

    def reset_interface(self, interface: Interface) -> None:
        """IFRS i — resetting RS232 drops our own connection. p. 58"""
        self._write(f"IFRS {_enum(interface, Interface, 'interface').value}")

    def go_to_local(self) -> None:
        """LCAL — re-enable the front panel. p. 59"""
        self._write("LCAL")

    def request_lock(self) -> bool:
        """LOCK? — True if the lock was granted. p. 59"""
        return _parse_int(self._query("LOCK?"), "LOCK?") == 1

    def go_to_remote(self) -> None:
        """REMT — lock out the front panel. p. 59"""
        self._write("REMT")

    def release_lock(self) -> bool:
        """UNLK? — True if the lock was released. p. 59"""
        return _parse_int(self._query("UNLK?"), "UNLK?") == 1

    def set_response_terminator(self, *codes: int) -> None:
        """XTRM i{,j,k} — 1 to 3 ASCII codes, default 13,10. p. 59

        The transport is switched to the new terminator as well. The last code
        should be a terminator the instrument actually ends lines with.
        """
        if not 1 <= len(codes) <= 3:
            raise ValueError(f"XTRM takes 1 to 3 codes, got {len(codes)}")
        values = [_int(c, "code", 0, 255) for c in codes]
        self._write(f"XTRM {','.join(map(str, values))}")
        self._transport.set_response_terminator(bytes(values))


# Mnemonic -> API methods implementing it. Used by the tests to prove that all
# 70 commands of the manual's command index (pp. 46–47) are covered.
COMMANDS: dict[str, tuple[str, ...]] = {
    "*CAL": ("auto_calibrate",),
    "*CLS": ("clear_status",),
    "*ESE": ("get_standard_event_status_enable", "set_standard_event_status_enable"),
    "*ESR": ("get_standard_event_status",),
    "*IDN": ("identify",),
    "*OPC": ("set_operation_complete_flag", "query_operation_complete"),
    "*PSC": ("get_power_on_status_clear", "set_power_on_status_clear"),
    "*RCL": ("recall_settings",),
    "*RST": ("reset",),
    "*SAV": ("save_settings",),
    "*SRE": ("get_service_request_enable", "set_service_request_enable"),
    "*STB": ("get_status_byte",),
    "*TRG": ("trigger",),
    "*TST": ("self_test",),
    "*WAI": ("wait",),
    "DISP": ("get_display", "set_display"),
    "INSE": ("get_instrument_status_enable", "set_instrument_status_enable"),
    "INSR": ("get_instrument_status",),
    "LERR": ("get_last_error",),
    "SHDP": ("get_display_enabled", "set_display_enabled"),
    "TIMB": ("get_timebase",),
    "ADVT": ("get_advanced_triggering", "set_advanced_triggering"),
    "HOLD": ("get_holdoff", "set_holdoff"),
    "INHB": ("get_inhibit", "set_inhibit"),
    "PHAS": ("get_prescale_phase", "set_prescale_phase"),
    "PRES": ("get_prescale_factor", "set_prescale_factor"),
    "SPHD": ("step_holdoff",),
    "SPPH": ("step_prescale_phase",),
    "SPPS": ("step_prescale_factor",),
    "SPTL": ("step_trigger_level",),
    "SPTR": ("step_trigger_rate",),
    "SSHD": ("get_holdoff_step_size", "set_holdoff_step_size"),
    "SSPH": ("get_prescale_phase_step_size", "set_prescale_phase_step_size"),
    "SSPS": ("get_prescale_factor_step_size", "set_prescale_factor_step_size"),
    "SSTL": ("get_trigger_level_step_size", "set_trigger_level_step_size"),
    "SSTR": ("get_trigger_rate_step_size", "set_trigger_rate_step_size"),
    "TLVL": ("get_trigger_level", "set_trigger_level"),
    "TRAT": ("get_trigger_rate", "set_trigger_rate"),
    "TSRC": ("get_trigger_source", "set_trigger_source"),
    "BURC": ("get_burst_count", "set_burst_count"),
    "BURD": ("get_burst_delay", "set_burst_delay"),
    "BURM": ("get_burst_mode", "set_burst_mode"),
    "BURP": ("get_burst_period", "set_burst_period"),
    "BURT": ("get_burst_t0_mode", "set_burst_t0_mode"),
    "SPBC": ("step_burst_count",),
    "SPBD": ("step_burst_delay",),
    "SPBP": ("step_burst_period",),
    "SSBC": ("get_burst_count_step_size", "set_burst_count_step_size"),
    "SSBD": ("get_burst_delay_step_size", "set_burst_delay_step_size"),
    "SSBP": ("get_burst_period_step_size", "set_burst_period_step_size"),
    "DLAY": ("get_delay", "set_delay"),
    "LAMP": ("get_amplitude", "set_amplitude"),
    "LINK": ("get_link", "set_link"),
    "LOFF": ("get_offset", "set_offset"),
    "LPOL": ("get_polarity", "set_polarity"),
    "SPDL": ("step_delay",),
    "SPLA": ("step_amplitude",),
    "SPLO": ("step_offset",),
    "SSDL": ("get_delay_step_size", "set_delay_step_size"),
    "SSLA": ("get_amplitude_step_size", "set_amplitude_step_size"),
    "SSLO": ("get_offset_step_size", "set_offset_step_size"),
    "EMAC": ("get_mac_address",),
    "EPHY": (
        "get_ethernet_auto_negotiation", "set_ethernet_auto_negotiation",
        "get_ethernet_link_speed", "set_ethernet_link_speed",
    ),
    "IFCF": ("get_interface_config", "set_interface_config"),
    "IFRS": ("reset_interface",),
    "LCAL": ("go_to_local",),
    "LOCK": ("request_lock",),
    "REMT": ("go_to_remote",),
    "UNLK": ("release_lock",),
    "XTRM": ("set_response_terminator",),
}
