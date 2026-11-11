"""Enumerations for every coded value in the DG645 remote interface.

Page numbers refer to the DG645 manual (documents/DG645_manual.pdf).
"""

from __future__ import annotations

from enum import IntEnum, IntFlag


# --- Generic ----------------------------------------------------------------

class State(IntEnum):
    """Off/on for ADVT, BURM, SHDP, EPHY 0 and the IFCF enable items."""

    OFF = 0
    ON = 1


class StepDirection(IntEnum):
    """Direction for all SP** step commands (pp. 53, 55, 57)."""

    DOWN = 0
    UP = 1


# --- Channels and outputs (Table 31, p. 56) ---------------------------------

class Channel(IntEnum):
    """Delay channel, parameters c and d."""

    T0 = 0
    T1 = 1
    A = 2
    B = 3
    C = 4
    D = 5
    E = 6
    F = 7
    G = 8
    H = 9


class Output(IntEnum):
    """Front-panel output BNC, parameter b."""

    T0 = 0
    AB = 1
    CD = 2
    EF = 3
    GH = 4


class Prescaler(IntEnum):
    """Prescaler for PRES/SPPS/SSPS (p. 53). PHAS/SPPH/SSPH accept AB–GH only (p. 52)."""

    TRIGGER = 0
    AB = 1
    CD = 2
    EF = 3
    GH = 4


class Polarity(IntEnum):
    """LPOL (p. 57)."""

    NEGATIVE = 0
    POSITIVE = 1


# --- Trigger and burst ------------------------------------------------------

class TriggerSource(IntEnum):
    """TSRC (p. 54)."""

    INTERNAL = 0
    EXTERNAL_RISING = 1
    EXTERNAL_FALLING = 2
    SINGLE_SHOT_EXTERNAL_RISING = 3
    SINGLE_SHOT_EXTERNAL_FALLING = 4
    SINGLE_SHOT = 5
    LINE = 6


class Inhibit(IntEnum):
    """INHB: what the rear-panel inhibit input suppresses (p. 52)."""

    OFF = 0
    TRIGGERS = 1
    AB = 2
    AB_CD = 3
    AB_CD_EF = 4
    AB_CD_EF_GH = 5


class BurstT0Mode(IntEnum):
    """BURT (p. 55)."""

    ALL_CYCLES = 0
    FIRST_CYCLE_ONLY = 1


# --- Status, display, system ------------------------------------------------

class PowerOnStatusClear(IntEnum):
    """*PSC (p. 49): whether *SRE/*ESE survive a power cycle."""

    RETAIN = 0
    CLEAR = 1


class Timebase(IntEnum):
    """TIMB? (p. 52)."""

    INTERNAL = 0
    OCXO = 1
    RUBIDIUM = 2
    EXTERNAL = 3


class Display(IntEnum):
    """DISP display type, parameter i (pp. 50–51)."""

    TRIGGER_RATE = 0
    TRIGGER_THRESHOLD = 1
    TRIGGER_SINGLE_SHOT = 2
    TRIGGER_LINE = 3
    ADVANCED_TRIGGERING = 4
    TRIGGER_HOLDOFF = 5
    PRESCALE_CONFIGURATION = 6
    BURST_MODE = 7
    BURST_DELAY = 8
    BURST_COUNT = 9
    BURST_PERIOD = 10
    CHANNEL_DELAY = 11
    CHANNEL_OUTPUT_LEVELS = 12
    CHANNEL_OUTPUT_POLARITY = 13
    BURST_T0_CONFIGURATION = 14


# --- Interfaces -------------------------------------------------------------

class Interface(IntEnum):
    """IFRS (p. 58)."""

    RS232 = 0
    GPIB = 1
    LAN = 2


class InterfaceConfig(IntEnum):
    """IFCF item, parameter i (p. 58)."""

    RS232_ENABLE = 0
    RS232_BAUD_RATE = 1
    GPIB_ENABLE = 2
    GPIB_ADDRESS = 3
    TCPIP_ENABLE = 4
    DHCP_ENABLE = 5
    AUTO_IP_ENABLE = 6
    STATIC_IP_ENABLE = 7
    BARE_SOCKET_ENABLE = 8
    TELNET_ENABLE = 9
    VXI11_ENABLE = 10
    STATIC_IP_ADDRESS = 11
    SUBNET_MASK = 12
    DEFAULT_GATEWAY = 13


class BaudRate(IntEnum):
    """Valid RS-232 baud rates (IFCF 1, p. 58)."""

    B4800 = 4800
    B9600 = 9600
    B19200 = 19200
    B38400 = 38400
    B57600 = 57600
    B115200 = 115200


class EthernetPhyItem(IntEnum):
    """EPHY item, parameter i (pp. 57–58)."""

    AUTO_NEGOTIATION = 0
    LINK_SPEED = 1


class LinkSpeed(IntEnum):
    """EPHY 1 value (p. 58; example 'EPHY 1,1' = 100 Base-T)."""

    BASE_T_10 = 0
    BASE_T_100 = 1


# --- Status registers (pp. 48–51, 60–61) ------------------------------------

class StatusByte(IntFlag):
    """*STB? / *SRE. Bit 2 is 'reserved' on p. 49 but BURST on p. 60."""

    INSB = 1 << 0
    BUSY = 1 << 1
    BURST = 1 << 2
    MAV = 1 << 4
    ESB = 1 << 5
    MSS = 1 << 6


class EventStatus(IntFlag):
    """*ESR? / *ESE."""

    OPC = 1 << 0
    QYE = 1 << 2
    DDE = 1 << 3
    EXE = 1 << 4
    CME = 1 << 5
    PON = 1 << 7


class InstrumentStatus(IntFlag):
    """INSR? / INSE."""

    TRIG = 1 << 0
    RATE = 1 << 1
    END_OF_DELAY = 1 << 2
    END_OF_BURST = 1 << 3
    INHIBIT = 1 << 4
    ABORT_DELAY = 1 << 5
    PLL_UNLOCK = 1 << 6
    RB_UNLOCK = 1 << 7


# --- Error codes (pp. 62–64) ------------------------------------------------

class ErrorCode(IntEnum):
    """Codes returned by LERR?, *TST? and *CAL?. ``description`` holds the manual's text."""

    description: str

    def __new__(cls, value: int, description: str):
        member = int.__new__(cls, value)
        member._value_ = value
        member.description = description
        return member

    # No error
    NO_ERROR = 0, "No more errors left in the queue."

    # Execution errors
    ILLEGAL_VALUE = 10, "A parameter was out of range."
    ILLEGAL_MODE = 11, "The action is illegal in the current mode."
    ILLEGAL_DELAY = 12, "The requested delay is out of range."
    ILLEGAL_LINK = 13, "The requested delay linkage is illegal."
    RECALL_FAILED = 14, "The recall of instrument settings from nonvolatile storage failed."
    NOT_ALLOWED = 15, "The instrument is locked by another interface."
    FAILED_SELF_TEST = 16, "The DG645 self test failed."
    FAILED_AUTO_CALIBRATION = 17, "The DG645 auto calibration failed."

    # Query errors
    LOST_DATA = 30, "Data in the output buffer was lost."
    NO_LISTENER = 32, "Addressed to talk on GPIB, but there are no listeners."

    # Device dependent errors
    FAILED_ROM_CHECK = 40, "The ROM checksum failed."
    FAILED_OFFSET_T0_TEST = 41, "Self test of offset functionality for output T0 failed."
    FAILED_OFFSET_AB_TEST = 42, "Self test of offset functionality for output AB failed."
    FAILED_OFFSET_CD_TEST = 43, "Self test of offset functionality for output CD failed."
    FAILED_OFFSET_EF_TEST = 44, "Self test of offset functionality for output EF failed."
    FAILED_OFFSET_GH_TEST = 45, "Self test of offset functionality for output GH failed."
    FAILED_AMPLITUDE_T0_TEST = 46, "Self test of amplitude functionality for output T0 failed."
    FAILED_AMPLITUDE_AB_TEST = 47, "Self test of amplitude functionality for output AB failed."
    FAILED_AMPLITUDE_CD_TEST = 48, "Self test of amplitude functionality for output CD failed."
    FAILED_AMPLITUDE_EF_TEST = 49, "Self test of amplitude functionality for output EF failed."
    FAILED_AMPLITUDE_GH_TEST = 50, "Self test of amplitude functionality for output GH failed."
    FAILED_FPGA_COMMUNICATIONS_TEST = 51, "Self test of FPGA communications failed."
    FAILED_GPIB_COMMUNICATIONS_TEST = 52, "Self test of GPIB communications failed."
    FAILED_DDS_COMMUNICATIONS_TEST = 53, "Self test of DDS communications failed."
    FAILED_SERIAL_EEPROM_COMMUNICATIONS_TEST = 54, "Self test of serial EEPROM communications failed."
    FAILED_TEMPERATURE_SENSOR_COMMUNICATIONS_TEST = 55, "Self test of the temperature sensor communications failed."
    FAILED_PLL_COMMUNICATIONS_TEST = 56, "Self test of PLL communications failed."
    FAILED_DAC0_COMMUNICATIONS_TEST = 57, "Self test of DAC 0 communications failed."
    FAILED_DAC1_COMMUNICATIONS_TEST = 58, "Self test of DAC 1 communications failed."
    FAILED_DAC2_COMMUNICATIONS_TEST = 59, "Self test of DAC 2 communications failed."
    FAILED_SAMPLE_AND_HOLD_OPERATIONS_TEST = 60, "Self test of sample and hold operations failed."
    FAILED_VJITTER_OPERATIONS_TEST = 61, "Self test of Vjitter operation failed."
    FAILED_CHANNEL_T0_ANALOG_DELAY_TEST = 62, "Self test of channel T0 analog delay failed."
    FAILED_CHANNEL_T1_ANALOG_DELAY_TEST = 63, "Self test of channel T1 analog delay failed."
    FAILED_CHANNEL_A_ANALOG_DELAY_TEST = 64, "Self test of channel A analog delay failed."
    FAILED_CHANNEL_B_ANALOG_DELAY_TEST = 65, "Self test of channel B analog delay failed."
    FAILED_CHANNEL_C_ANALOG_DELAY_TEST = 66, "Self test of channel C analog delay failed."
    FAILED_CHANNEL_D_ANALOG_DELAY_TEST = 67, "Self test of channel D analog delay failed."
    FAILED_CHANNEL_E_ANALOG_DELAY_TEST = 68, "Self test of channel E analog delay failed."
    FAILED_CHANNEL_F_ANALOG_DELAY_TEST = 69, "Self test of channel F analog delay failed."
    FAILED_CHANNEL_G_ANALOG_DELAY_TEST = 70, "Self test of channel G analog delay failed."
    FAILED_CHANNEL_H_ANALOG_DELAY_TEST = 71, "Self test of channel H analog delay failed."
    FAILED_SAMPLE_AND_HOLD_CALIBRATION = 80, "Auto calibration of sample and hold DAC failed."
    FAILED_T0_CALIBRATION = 81, "Auto calibration of channel T0 failed."
    FAILED_T1_CALIBRATION = 82, "Auto calibration of channel T1 failed."
    FAILED_A_CALIBRATION = 83, "Auto calibration of channel A failed."
    FAILED_B_CALIBRATION = 84, "Auto calibration of channel B failed."
    FAILED_C_CALIBRATION = 85, "Auto calibration of channel C failed."
    FAILED_D_CALIBRATION = 86, "Auto calibration of channel D failed."
    FAILED_E_CALIBRATION = 87, "Auto calibration of channel E failed."
    FAILED_F_CALIBRATION = 88, "Auto calibration of channel F failed."
    FAILED_G_CALIBRATION = 89, "Auto calibration of channel G failed."
    FAILED_H_CALIBRATION = 90, "Auto calibration of channel H failed."
    FAILED_VJITTER_CALIBRATION = 91, "Auto calibration of Vjitter failed."

    # Parsing errors
    ILLEGAL_COMMAND = 110, "The command syntax used was illegal."
    UNDEFINED_COMMAND = 111, "The specified command does not exist."
    ILLEGAL_QUERY = 112, "The specified command does not permit queries."
    ILLEGAL_SET = 113, "The specified command can only be queried."
    NULL_PARAMETER = 114, "The parser detected an empty parameter."
    EXTRA_PARAMETERS = 115, "The parser detected more parameters than allowed by the command."
    MISSING_PARAMETERS = 116, "The parser detected missing parameters required by the command."
    PARAMETER_OVERFLOW = 117, "The buffer for storing parameter values overflowed."
    INVALID_FLOATING_POINT_NUMBER = 118, "The parser expected a floating point number, but was unable to parse it."
    INVALID_INTEGER = 120, "The parser expected an integer, but was unable to parse it."
    INTEGER_OVERFLOW = 121, "A parsed integer was too large to store correctly."
    INVALID_HEXADECIMAL = 122, "The parser expected hexadecimal characters but was unable to parse them."
    SYNTAX_ERROR = 126, "The parser detected a syntax error in the command."

    # Communication errors
    COMMUNICATION_ERROR = 170, "A framing or parity error was detected in the data stream."
    OVER_RUN = 171, "The input buffer of the remote interface overflowed."

    # Other errors
    TOO_MANY_ERRORS = 254, "The error buffer is full. Subsequent errors have been dropped."
