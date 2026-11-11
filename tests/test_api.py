"""Checks the API against the DG645 manual: wire strings, reply parsing, limits, coverage."""

from decimal import Decimal
from ipaddress import IPv4Address

import pytest

from dg645 import (
    COMMANDS,
    LONG_OPERATION_TIMEOUT_S,
    BaudRate,
    BurstT0Mode,
    Channel,
    DelaySetting,
    DG645Api,
    DG645ResponseError,
    Display,
    DisplaySetting,
    ErrorCode,
    EventStatus,
    Identification,
    Inhibit,
    InstrumentStatus,
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


class FakeTransport:
    def __init__(self):
        self.sent: list[str] = []
        self.replies: list[str] = []
        self.terminator = b"\r\n"
        self.timeouts: list[float | None] = []

    def write(self, command: str) -> None:
        self.sent.append(command)

    def query(self, command: str, timeout_s: float | None = None) -> str:
        self.sent.append(command)
        self.timeouts.append(timeout_s)
        return self.replies.pop(0)

    def set_response_terminator(self, terminator: bytes) -> None:
        self.terminator = terminator

    def close(self) -> None:
        pass


@pytest.fixture
def io():
    return FakeTransport()


@pytest.fixture
def api(io):
    return DG645Api(io)


# --- Coverage -------------------------------------------------------------------

MANUAL_INDEX = """
*CAL *CLS *ESE *ESR *IDN *OPC *PSC *RCL *RST *SAV *SRE *STB *TRG *TST *WAI
DISP INSE INSR LERR SHDP TIMB
ADVT HOLD INHB PHAS PRES SPHD SPPH SPPS SPTL SPTR SSHD SSPH SSPS SSTL SSTR TLVL TRAT TSRC
BURC BURD BURM BURP BURT SPBC SPBD SPBP SSBC SSBD SSBP
DLAY LAMP LINK LOFF LPOL SPDL SPLA SPLO SSDL SSLA SSLO
EMAC EPHY IFCF IFRS LCAL LOCK REMT UNLK XTRM
""".split()


def test_all_70_manual_commands_are_mapped():
    assert len(MANUAL_INDEX) == 70
    assert set(COMMANDS) == set(MANUAL_INDEX)


def test_every_mapped_method_exists():
    for mnemonic, methods in COMMANDS.items():
        for name in methods:
            assert callable(getattr(DG645Api, name, None)), f"{mnemonic}: {name} missing"


# --- Manual examples (exact command strings) ------------------------------------

@pytest.mark.parametrize("call, expected", [
    (lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("10e-6")), "DLAY 2,0,0.000010000000"),  # p. 56
    (lambda a: a.set_delay(Channel.B, Channel.A, Decimal("1e-3")), "DLAY 3,2,0.001000000000"),  # p. 56
    (lambda a: a.set_amplitude(Output.CD, Decimal("3.5")), "LAMP 2,3.50"),  # p. 56
    (lambda a: a.set_link(Channel.B, Channel.A), "LINK 3,2"),                               # p. 57
    (lambda a: a.set_offset(Output.T0, Decimal("-1.0")), "LOFF 0,-1.00"),  # p. 57
    (lambda a: a.set_polarity(Output.AB, Polarity.NEGATIVE), "LPOL 1,0"),                   # p. 57
    (lambda a: a.set_holdoff(Decimal("1e-6")), "HOLD 0.000001"),                            # p. 52
    (lambda a: a.set_inhibit(Inhibit.AB), "INHB 2"),                                        # p. 52
    (lambda a: a.set_prescale_factor(Prescaler.TRIGGER, 100), "PRES 0,100"),                # p. 53
    (lambda a: a.set_prescale_factor(Prescaler.AB, 5), "PRES 1,5"),                         # p. 53
    (lambda a: a.set_trigger_rate(Decimal("1e3")), "TRAT 1000.000000"),  # p. 54
    (lambda a: a.set_trigger_source(TriggerSource.SINGLE_SHOT), "TSRC 5"),                  # p. 54
    (lambda a: a.set_burst_count(10), "BURC 10"),                                           # p. 54
    (lambda a: a.set_burst_delay(Decimal("5e-6")), "BURD 0.000005000000"),  # p. 55
    (lambda a: a.set_burst_period(Decimal("1e-3")), "BURP 0.001000000"),  # p. 55
    (lambda a: a.set_display(Display.CHANNEL_DELAY, Channel.A), "DISP 11,2"),               # p. 51
    (lambda a: a.set_display(Display.CHANNEL_OUTPUT_LEVELS, Channel.C), "DISP 12,4"),       # p. 51
    (lambda a: a.set_display(Display.CHANNEL_OUTPUT_POLARITY, Channel.D), "DISP 13,5"),     # p. 51
    (lambda a: a.set_power_on_status_clear(PowerOnStatusClear.CLEAR), "*PSC 1"),  # p. 49
    (lambda a: a.recall_settings(3), "*RCL 3"),                                             # p. 49
    (lambda a: a.save_settings(3), "*SAV 3"),                                               # p. 49
    (lambda a: a.set_ethernet_auto_negotiation(State.OFF), "EPHY 0,0"),                     # p. 58
    (lambda a: a.set_ethernet_link_speed(LinkSpeed.BASE_T_100), "EPHY 1,1"),                # p. 58
    (lambda a: a.set_interface_config(InterfaceConfig.AUTO_IP_ENABLE, State.OFF), "IFCF 6,0"),        # p. 58
    (lambda a: a.set_interface_config(InterfaceConfig.RS232_BAUD_RATE, BaudRate.B19200), "IFCF 1,19200"),
    (lambda a: a.set_interface_config(InterfaceConfig.GPIB_ADDRESS, 16), "IFCF 3,16"),
    (lambda a: a.set_interface_config(InterfaceConfig.STATIC_IP_ADDRESS, IPv4Address("192.168.10.5")),
     "IFCF 11,192.168.10.5"),
    (lambda a: a.set_interface_config(InterfaceConfig.SUBNET_MASK, IPv4Address("255.255.255.0")),
     "IFCF 12,255.255.255.0"),
    (lambda a: a.set_interface_config(InterfaceConfig.DEFAULT_GATEWAY, IPv4Address("192.168.10.1")),
     "IFCF 13,192.168.10.1"),
    (lambda a: a.reset(), "*RST"),
    (lambda a: a.wait(), "*WAI"),
    (lambda a: a.trigger(), "*TRG"),
    (lambda a: a.go_to_remote(), "REMT"),
    (lambda a: a.go_to_local(), "LCAL"),
])
def test_manual_examples(api, io, call, expected):
    call(api)
    assert io.sent == [expected]


# --- Reply parsing --------------------------------------------------------------

def test_delay_reply_from_manual(api, io):
    io.replies = ["2,+0.001000000000"]  # p. 56
    assert api.get_delay(Channel.B) == DelaySetting(Channel.A, Decimal("0.001"))
    assert io.sent == ["DLAY?3"]


def test_delay_keeps_full_precision(api, io):
    io.replies = ["0,+1999.999999999995"]
    assert api.get_delay(Channel.H).offset == Decimal("1999.999999999995")


def test_link_reply_from_manual(api, io):
    io.replies = ["2"]  # p. 57
    assert api.get_link(Channel.B) is Channel.A
    assert io.sent == ["LINK?3"]


def test_amplitude_query_string_from_manual(api, io):
    io.replies = ["+2.50"]
    assert api.get_amplitude(Output.EF) == Decimal("2.50")
    assert io.sent == ["LAMP?3"]  # p. 56


def test_identify_example_from_manual(api, io):
    io.replies = ["Stanford Research Systems,DG645,s/n004025,ver1.00.00E"]  # p. 48
    assert api.identify() == Identification("Stanford Research Systems", "DG645", "s/n004025", "ver1.00.00E")


def test_esr_example_from_manual(api, io):
    io.replies = ["176"]  # p. 48: PON, CME, EXE
    assert api.get_standard_event_status() == EventStatus.PON | EventStatus.CME | EventStatus.EXE


def test_stb_example_from_manual(api, io):
    io.replies = ["113"]  # p. 50: INSB, MAV, ESB, MSS
    assert api.get_status_byte() == StatusByte.INSB | StatusByte.MAV | StatusByte.ESB | StatusByte.MSS


def test_insr_example_from_manual(api, io):
    io.replies = ["5"]  # p. 51: triggered and delay cycle completed
    assert api.get_instrument_status() == InstrumentStatus.TRIG | InstrumentStatus.END_OF_DELAY


def test_enum_replies(api, io):
    io.replies = ["5", "2", "1", "3", "1", "1"]
    assert api.get_trigger_source() is TriggerSource.SINGLE_SHOT
    assert api.get_timebase() is Timebase.RUBIDIUM
    assert api.get_burst_t0_mode() is BurstT0Mode.FIRST_CYCLE_ONLY
    assert api.get_inhibit() is Inhibit.AB_CD
    assert api.get_polarity(Output.GH) is Polarity.POSITIVE
    assert api.get_advanced_triggering() is State.ON


def test_display_reply(api, io):
    io.replies = ["11,2"]
    assert api.get_display() == DisplaySetting(Display.CHANNEL_DELAY, Channel.A)


def test_interface_config_replies(api, io):
    io.replies = ["1", "115200", "15", "192.168.10.5"]
    assert api.get_interface_config(InterfaceConfig.RS232_ENABLE) is State.ON
    assert api.get_interface_config(InterfaceConfig.RS232_BAUD_RATE) is BaudRate.B115200
    assert api.get_interface_config(InterfaceConfig.GPIB_ADDRESS) == 15
    assert api.get_interface_config(InterfaceConfig.STATIC_IP_ADDRESS) == IPv4Address("192.168.10.5")


def test_error_queue(api, io):
    io.replies = ["12", "111", "0"]
    assert api.read_error_queue() == [ErrorCode.ILLEGAL_DELAY, ErrorCode.UNDEFINED_COMMAND]


def test_self_test_and_calibration(api, io):
    io.replies = ["0", "17"]
    assert api.self_test() is ErrorCode.NO_ERROR
    assert api.auto_calibrate() is ErrorCode.FAILED_AUTO_CALIBRATION


def test_lock(api, io):
    io.replies = ["1", "0"]
    assert api.request_lock() is True
    assert api.release_lock() is False


@pytest.mark.parametrize("reply", ["", "abc", "99"])
def test_invalid_enum_reply_raises(api, io, reply):
    io.replies = [reply]
    with pytest.raises(DG645ResponseError):
        api.get_trigger_source()


def test_malformed_delay_reply_raises(api, io):
    io.replies = ["+0.001"]
    with pytest.raises(DG645ResponseError):
        api.get_delay(Channel.A)


# --- Types ----------------------------------------------------------------------

def test_floats_are_rejected(api):
    with pytest.raises(TypeError):
        api.set_trigger_rate(1000.0)
    with pytest.raises(TypeError):
        api.set_delay(Channel.A, Channel.T0, 1e-6)


def test_plain_ints_are_rejected_where_enums_are_required(api):
    with pytest.raises(TypeError):
        api.set_trigger_source(5)
    with pytest.raises(TypeError):
        api.set_delay(2, Channel.T0, Decimal("0"))


def test_bool_is_not_an_int(api):
    with pytest.raises(TypeError):
        api.set_burst_count(True)


def test_wrong_enum_type_rejected(api):
    with pytest.raises(TypeError):
        api.set_amplitude(Channel.A, Decimal("2"))  # Output expected


# --- Limits ---------------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("2000")),
    lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("1999.9999999999976")),  # rounds to 2000
    lambda a: a.set_delay(Channel.T0, Channel.A, Decimal("0")),           # T0 is predefined
    lambda a: a.set_delay(Channel.T1, Channel.A, Decimal("0")),           # T1 is predefined
    lambda a: a.set_delay(Channel.A, Channel.A, Decimal("0")),
    lambda a: a.set_link(Channel.A, Channel.T1),
    lambda a: a.set_trigger_rate(Decimal("0.00009")),
    lambda a: a.set_trigger_rate(Decimal("10000000.000001")),
    lambda a: a.set_trigger_level(Decimal("3.51")),
    lambda a: a.set_amplitude(Output.AB, Decimal("0.494")),               # rounds to 0.49
    lambda a: a.set_amplitude(Output.AB, Decimal("5.01")),
    lambda a: a.set_offset(Output.AB, Decimal("-2.01")),
    lambda a: a.set_burst_count(0),
    lambda a: a.set_burst_count(2**32),
    lambda a: a.set_burst_period(Decimal("94E-9")),                       # rounds to 90 ns
    lambda a: a.set_burst_delay(Decimal("-5E-12")),
    lambda a: a.set_prescale_factor(Prescaler.TRIGGER, 2**30),
    lambda a: a.set_prescale_factor(Prescaler.AB, 2**16),
    lambda a: a.set_prescale_phase(Prescaler.TRIGGER, 0),                 # phase has no trigger prescaler
    lambda a: a.save_settings(0),
    lambda a: a.recall_settings(10),
    lambda a: a.set_interface_config(InterfaceConfig.GPIB_ADDRESS, 31),
    lambda a: a.set_interface_config(InterfaceConfig.RS232_BAUD_RATE, 9600),
    lambda a: a.set_response_terminator(),
    lambda a: a.set_holdoff(Decimal("-1")),
    lambda a: a.set_delay_step_size(Channel.A, Decimal("2E-12")),         # rounds to 0
])
def test_out_of_range_rejected_before_sending(api, io, call):
    with pytest.raises((ValueError, TypeError)):
        call(api)
    assert io.sent == []


def test_limits_are_inclusive(api, io):
    api.set_delay(Channel.A, Channel.T0, Decimal("1999.999999999995"))
    api.set_delay(Channel.G, Channel.F, Decimal("-0.1"))  # negative relative delay, Table 12 p. 27
    api.set_trigger_rate(Decimal("0.0001"))
    api.set_trigger_rate(Decimal("10000000"))
    api.set_amplitude(Output.GH, Decimal("0.5"))
    api.set_offset(Output.GH, Decimal("-2.0"))
    api.set_burst_count(2**32 - 1)
    api.set_burst_period(Decimal("100E-9"))
    api.set_prescale_factor(Prescaler.TRIGGER, 2**30 - 1)
    assert io.sent == [
        "DLAY 2,0,1999.999999999995",
        "DLAY 8,7,-0.100000000000",
        "TRAT 0.000100",
        "TRAT 10000000.000000",
        "LAMP 4,0.50",
        "LOFF 4,-2.00",
        "BURC 4294967295",
        "BURP 0.000000100",
        "PRES 0,1073741823",
    ]


# --- Rounding to the documented grid ----------------------------------------------

@pytest.mark.parametrize("call, sent, returned", [
    # delays: 5 ps grid, half up
    (lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("1E-12")), "DLAY 2,0,0.000000000000", "0"),
    (lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("2.4E-12")), "DLAY 2,0,0.000000000000", "0"),
    (lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("2.5E-12")), "DLAY 2,0,0.000000000005", "5E-12"),
    (lambda a: a.set_delay(Channel.A, Channel.T0, Decimal("0.123456789123")),
     "DLAY 2,0,0.123456789125", "0.123456789125"),
    (lambda a: a.set_delay(Channel.G, Channel.F, Decimal("-1E-12")), "DLAY 8,7,0.000000000000", "0"),  # no "-0"
    (lambda a: a.set_delay(Channel.G, Channel.F, Decimal("-3E-12")), "DLAY 8,7,-0.000000000005", "-5E-12"),
    (lambda a: a.set_burst_delay(Decimal("7E-12")), "BURD 0.000000000005", "5E-12"),
    (lambda a: a.set_delay_step_size(Channel.A, Decimal("3E-12")), "SSDL 2,0.000000000005", "5E-12"),
    # burst period: 10 ns grid
    (lambda a: a.set_burst_period(Decimal("105E-9")), "BURP 0.000000110", "110E-9"),
    (lambda a: a.set_burst_period(Decimal("104.9E-9")), "BURP 0.000000100", "100E-9"),
    # trigger rate: 1 µHz grid
    (lambda a: a.set_trigger_rate(Decimal("1.0000005")), "TRAT 1.000001", "1.000001"),
    # output levels: 0.01 V grid
    (lambda a: a.set_amplitude(Output.AB, Decimal("2.505")), "LAMP 1,2.51", "2.51"),
    (lambda a: a.set_amplitude(Output.AB, Decimal("0.495")), "LAMP 1,0.50", "0.5"),
    (lambda a: a.set_offset(Output.AB, Decimal("-0.004")), "LOFF 1,0.00", "0"),
])
def test_values_are_rounded_to_resolution(api, io, call, sent, returned):
    assert call(api) == Decimal(returned)
    assert io.sent == [sent]


def test_values_without_documented_resolution_are_sent_unchanged(api, io):
    assert api.set_trigger_level(Decimal("1.234")) == Decimal("1.234")
    assert api.set_holdoff(Decimal("0.0000123456789")) == Decimal("0.0000123456789")
    assert io.sent == ["TLVL 1.234", "HOLD 0.0000123456789"]


def test_xtrm_updates_transport(api, io):
    api.set_response_terminator(13, 10)
    assert io.sent == ["XTRM 13,10"]
    assert io.terminator == b"\r\n"


# --- Enums ----------------------------------------------------------------------

def test_error_codes_match_manual():
    assert len(ErrorCode) == 71
    assert ErrorCode(15) is ErrorCode.NOT_ALLOWED
    assert ErrorCode.ILLEGAL_DELAY.description == "The requested delay is out of range."
    assert ErrorCode.FAILED_CHANNEL_H_ANALOG_DELAY_TEST == 71
    assert ErrorCode.FAILED_H_CALIBRATION == 90
    assert ErrorCode.TOO_MANY_ERRORS == 254


def test_long_running_queries_use_long_timeout(io):
    api = DG645Api(io)
    io.replies += ["0", "0", "1", "1"]
    api.self_test()
    api.auto_calibrate()
    api.query_operation_complete()
    api.query_operation_complete(timeout_s=5.0)
    assert io.timeouts == [LONG_OPERATION_TIMEOUT_S, LONG_OPERATION_TIMEOUT_S, None, 5.0]
