"""DigitalDelayGenerator against a scripted fake instrument (no hardware needed)."""

import threading
from decimal import Decimal

import pytest

from dg645 import (
    Channel,
    DelaySetting,
    DG645CommunicationError,
    DG645InstrumentError,
    DG645ModeError,
    DG645VerificationError,
    DigitalDelayGenerator,
    ErrorCode,
    Output,
    State,
    TriggerSource,
)

IDN = "Stanford Research Systems,DG645,s/n004025,ver1.00.00E"


class FakeInstrument:
    """Answers queries from ``answers``; a list value is consumed one reply at a time.

    LERR? answers 0 (no error) unless scripted otherwise.
    """

    def __init__(self, **answers):
        self.answers = {"*IDN?": IDN, "LOCK?": "1", "UNLK?": "1", "LERR?": "0", **answers}
        self.sent: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.sent.append(command)

    def query(self, command: str, timeout_s: float | None = None) -> str:
        self.sent.append(command)
        key = command if command in self.answers else command.rstrip("0123456789")
        answer = self.answers[key]
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    def set_response_terminator(self, terminator: bytes) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def connect(fake, **kwargs):
    ddg = DigitalDelayGenerator.from_transport(fake, **kwargs)
    fake.sent.clear()
    return ddg


def test_connect_sequence():
    fake = FakeInstrument()
    DigitalDelayGenerator.from_transport(fake)
    assert fake.sent == ["*IDN?", "*CLS", "LOCK?", "REMT", "LERR?"]


def test_self_test_runs_before_lock():
    fake = FakeInstrument(**{"*TST?": "0"})
    DigitalDelayGenerator.from_transport(fake, self_test=True)
    assert fake.sent == ["*IDN?", "*CLS", "*TST?", "LERR?", "LOCK?", "REMT", "LERR?"]


def test_failed_self_test_raises_with_codes_and_closes():
    fake = FakeInstrument(**{"*TST?": "16", "LERR?": ["43", "0"]})
    with pytest.raises(DG645InstrumentError) as info:
        DigitalDelayGenerator.from_transport(fake, self_test=True)
    assert info.value.errors == (ErrorCode.FAILED_SELF_TEST, ErrorCode(43))
    assert fake.closed
    assert "UNLK?" not in fake.sent


def test_wrong_model_is_rejected():
    fake = FakeInstrument(**{"*IDN?": "Stanford Research Systems,DG535,s/n1,ver1"})
    with pytest.raises(DG645CommunicationError):
        DigitalDelayGenerator.from_transport(fake)
    assert fake.closed


def test_refused_lock_raises():
    fake = FakeInstrument(**{"LOCK?": "0"})
    with pytest.raises(DG645InstrumentError):
        DigitalDelayGenerator.from_transport(fake)
    assert fake.closed
    assert "REMT" not in fake.sent and "UNLK?" not in fake.sent


def test_close_releases_lock_and_front_panel_once():
    fake = FakeInstrument()
    with connect(fake):
        pass
    assert fake.sent == ["UNLK?", "LCAL"]
    assert fake.closed


def test_set_checks_error_queue():
    fake = FakeInstrument()
    ddg = connect(fake)
    ddg.trigger.source = TriggerSource.INTERNAL
    assert fake.sent == ["TSRC 0", "LERR?"]


def test_instrument_error_is_raised():
    fake = FakeInstrument()
    ddg = connect(fake)
    fake.answers["LERR?"] = ["12", "0"]
    with pytest.raises(DG645InstrumentError) as info:
        ddg.channels[Channel.B].delay = DelaySetting(Channel.A, Decimal("1E-6"))
    assert info.value.errors == (ErrorCode.ILLEGAL_DELAY,)


def test_no_read_back_without_verify():
    fake = FakeInstrument()
    ddg = connect(fake)
    ddg.outputs[Output.AB].amplitude = Decimal("2.5")
    assert fake.sent == ["LAMP 1,2.50", "LERR?"]


def test_read_back_compares_rounded_value():
    fake = FakeInstrument(**{"DLAY?": "2,+0.000001000005"})
    ddg = connect(fake, verify=True)
    ddg.channels[Channel.B].delay = DelaySetting(Channel.A, Decimal("1.0000047E-6"))
    assert fake.sent == ["DLAY 3,2,0.000001000005", "LERR?", "DLAY?3"]


def test_read_back_mismatch_raises():
    fake = FakeInstrument(**{"TRAT?": "999.000000"})
    ddg = connect(fake, verify=True)
    with pytest.raises(DG645VerificationError):
        ddg.trigger.rate = Decimal(1000)


def test_holdoff_needs_advanced_triggering():
    fake = FakeInstrument(**{"ADVT?": "0"})
    ddg = connect(fake)
    with pytest.raises(DG645ModeError):
        ddg.trigger.holdoff = Decimal("1E-6")
    assert fake.sent == ["ADVT?"]

    fake.answers["ADVT?"] = "1"
    ddg.outputs[Output.CD].prescale = 100
    assert fake.sent[-3:] == ["ADVT?", "PRES 2,100", "LERR?"]


def test_t0_has_no_output_prescaler():
    ddg = connect(FakeInstrument())
    with pytest.raises(DG645ModeError):
        ddg.outputs[Output.T0].phase = 1


def test_channels_are_a_to_h():
    ddg = connect(FakeInstrument())
    assert list(ddg.channels) == [Channel(i) for i in range(2, 10)]


def test_set_and_error_check_are_not_interleaved():
    fake = FakeInstrument()
    ddg = connect(fake)

    def worker(state):
        for _ in range(200):
            ddg.burst.enabled = state

    threads = [threading.Thread(target=worker, args=(s,)) for s in State]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(fake.sent[i + 1] == "LERR?" for i in range(0, len(fake.sent), 2))
