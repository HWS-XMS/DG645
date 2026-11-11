"""Python library for the SRS DG645 digital delay generator (RS-232 via pyserial)."""

from .api import COMMANDS, LONG_OPERATION_TIMEOUT_S, DelaySetting, DG645Api, DisplaySetting, Identification
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
from .ddg import Burst, DelayChannel, DigitalDelayGenerator, OutputControl, Trigger
from .errors import (
    DG645CommunicationError,
    DG645Error,
    DG645InstrumentError,
    DG645ModeError,
    DG645ResponseError,
    DG645VerificationError,
)
from .transport import SerialTransport, Transport

__all__ = [
    "COMMANDS", "LONG_OPERATION_TIMEOUT_S", "DelaySetting", "DG645Api", "DisplaySetting", "Identification",
    "BaudRate", "BurstT0Mode", "Channel", "Display", "ErrorCode", "EthernetPhyItem",
    "EventStatus", "Inhibit", "InstrumentStatus", "Interface", "InterfaceConfig",
    "LinkSpeed", "Output", "Polarity", "PowerOnStatusClear", "Prescaler", "State",
    "StatusByte", "StepDirection", "Timebase", "TriggerSource",
    "Burst", "DelayChannel", "DigitalDelayGenerator", "OutputControl", "Trigger",
    "DG645CommunicationError", "DG645Error", "DG645InstrumentError", "DG645ModeError",
    "DG645ResponseError", "DG645VerificationError",
    "SerialTransport", "Transport",
]
