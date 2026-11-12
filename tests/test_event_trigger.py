import pytest

from conftest import ReplayTransport, acknowledgement, ascii_message
from um982py import Log, Receiver
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.protocol.ascii import parse_ascii
from um982py.receiver_models import LogList
from um982py.subscriptions import temporary_subscriptions


def test_eventflag_once_receives_the_native_event() -> None:
    command = "EVENTFLAGA COM2 ONCE"
    event = ascii_message("EVENTFLAGA", "2,43,0,0,2227,210351,999532091,0,-1,-1")
    transport = ReplayTransport(
        {f"{command}\r\n".encode(): acknowledgement(command) + event}, chunk=65536
    )
    with Receiver(transport, timeout=1) as receiver:
        assert receiver.execute(
            Log.EVENTFLAG.output(Trigger.ONCE, port=Port.COM2)
        ).accepted
        record = Log.EVENTFLAG.decode(receiver.receive())
    assert transport.writes == [f"{command}\r\n".encode()]
    assert record.integer("event_id") == 2
    assert record.integer("week") == 2227
    assert record.integer("second") == 210351
    assert record.integer("subsecond") == 999532091


def test_once_only_applies_to_documented_eventflag_output() -> None:
    assert Log.EVENTFLAG.output(Trigger.ONCE, binary=True).text == "EVENTFLAGB ONCE"
    assert Log.EVENTFLAG.output(Trigger.ON_CHANGED).text == "EVENTFLAGA ONCHANGED"
    for log in (Log.EVENTSLN, Log.OBSVBASE, Log.GPGGA):
        with pytest.raises(ValueError, match="ONCE"):
            log.output(Trigger.ONCE)
    with pytest.raises(ValueError, match="interval or rate_hz"):
        Log.EVENTFLAG.output(Trigger.ONCE, rate_hz=1)


def test_once_loglist_trigger_is_preserved_for_restoration() -> None:
    message = parse_ascii(ascii_message("LOGLISTA", '1,"EVENTFLAGB COM1 ONCE"'))
    entry = LogList.from_message(message).entries[0]
    assert entry.interval is Trigger.ONCE
    assert entry.rate_hz is None
    assert entry.command().text == "EVENTFLAGB COM1 ONCE"


@pytest.mark.parametrize("port", [None, Port.COM1])
def test_temporary_capture_does_not_replace_pending_once_log(port: Port | None) -> None:
    logs = ascii_message("LOGLISTA", '1,"EVENTFLAGB COM1 ONCE"')
    transport = ReplayTransport({b"LOGLISTA\r\n": logs})
    command = Log.EVENTFLAG.output(Trigger.ON_CHANGED, binary=True, port=port)
    with (
        Receiver(transport, timeout=1) as receiver,
        pytest.raises(ProtocolError, match="pending ONCE"),
        temporary_subscriptions(receiver, ("EVENTFLAGB", command)),
    ):
        pytest.fail("pending one-shot subscription was replaced")
    assert transport.writes == [b"LOGLISTA\r\n"]


def test_temporary_capture_can_use_an_unrelated_port() -> None:
    logs = ascii_message("LOGLISTA", '1,"EVENTFLAGB COM1 ONCE"')
    command = Log.EVENTFLAG.output(Trigger.ON_CHANGED, binary=True, port=Port.COM2)
    start = command.text
    stop = "UNLOG COM2 EVENTFLAGB"
    transport = ReplayTransport(
        {
            b"LOGLISTA\r\n": logs,
            f"{start}\r\n".encode(): acknowledgement(start),
            f"{stop}\r\n".encode(): acknowledgement(stop),
        }
    )
    with (
        Receiver(transport, timeout=1) as receiver,
        temporary_subscriptions(receiver, ("EVENTFLAGB", command)),
    ):
        pass
    assert transport.writes == [
        b"LOGLISTA\r\n",
        f"{start}\r\n".encode(),
        f"{stop}\r\n".encode(),
    ]
