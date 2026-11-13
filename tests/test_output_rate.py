"""Documented N4 output rates across logs, antennas and receiver APIs."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import SubscriptionTransport
from um982py import AsyncReceiver, Log, Receiver, ReceiverStream, Rover, capture_live
from um982py.antenna import AntennaLog, antenna_log
from um982py.capture import subscription_plan
from um982py.cli import main
from um982py.commands.core import action
from um982py.commands.types import Port, Trigger
from um982py.errors import CommandRejected, ProtocolError
from um982py.receiver_models import LogEntry
from um982py.stream_capture import iter_live_records


@pytest.mark.parametrize(
    ("rate", "period"),
    [(1, "1"), (2, "0.5"), (5, "0.2"), (10, "0.1"), (20, "0.05"), (50, "0.02")],
)
@pytest.mark.parametrize("log", [Log.GPGGA, Log.BESTNAV, Log.RANGE, Log.RTCM1074])
def test_rate_commands_for_all_log_families(log: Log, rate: float, period: str) -> None:
    assert (
        log.output(rate_hz=rate, port=Port.COM2).text
        == f"{log.wire_name()} COM2 {period}"
    )


@pytest.mark.parametrize(
    "rate", [True, False, 0, -1, 7, 25, 100, float("inf"), float("nan")]
)
def test_unsupported_rates_are_rejected(rate: float) -> None:
    with pytest.raises(ValueError, match="rate_hz"):
        Log.GPGGA.output(rate_hz=rate)


@pytest.mark.parametrize(
    "log",
    [Log.FREQJAMSTATUS, Log.HWSTATUS, Log.JAMSTATUS, Log.PPSSTATUS, Log.RTCSTATUS],
)
def test_status_logs_limit_periodic_output_to_at_most_one_hertz(log: Log) -> None:
    for interval in (0.05, 0.5, 0.999):
        with pytest.raises(ValueError, match="at most 1 Hz"):
            log.output(interval)
    for rate in (2, 5, 10, 20, 50):
        with pytest.raises(ValueError, match="at most 1 Hz"):
            log.output(rate_hz=rate, binary=True)
    assert log.output(rate_hz=1).text == f"{log.wire_name()} 1"
    assert log.output(5, binary=True).text == f"{log.wire_name(binary=True)} 5"
    assert log.request().text == log.wire_name()
    assert action(f"{log.wire_name()} 0.1").text.endswith(" 0.1")


def test_status_rate_limit_prevalidates_batches_and_capture_plans() -> None:
    transport = SubscriptionTransport()
    with Receiver(transport) as receiver:
        with pytest.raises(ValueError, match="HWSTATUS supports at most 1 Hz"):
            receiver.set_output_rate([Log.GPGGA, Log.HWSTATUS], 10)
        with pytest.raises(ValueError, match="JAMSTATUS supports at most 1 Hz"):
            capture_live(receiver, [Log.BESTNAV, Log.JAMSTATUS], duration=1, rate_hz=10)
        with pytest.raises(ValueError, match="RTCSTATUS supports at most 1 Hz"):
            subscription_plan([Log.BESTNAV, Log.RTCSTATUS], interval=0.1, binary=True)
    assert transport.writes == []


def test_output_options_and_event_logs_are_not_silently_rewritten() -> None:
    with pytest.raises(ValueError, match="interval or rate_hz"):
        Log.GPGGA.output(1, rate_hz=10)
    with pytest.raises(ValueError, match="interval or rate_hz"):
        Log.OBSVBASE.output(Trigger.ON_CHANGED, rate_hz=10)
    with pytest.raises(ValueError, match="ONCHANGED"):
        Log.OBSVBASE.output(rate_hz=10)
    assert Log.GPGGA.output().text == "GPGGA 1"
    assert Log.GPGGA.output(10).text == "GPGGA 10"
    assert Log.OBSVBASE.output(Trigger.ON_CHANGED).text == "OBSVBASEA ONCHANGED"
    secondary = antenna_log(Log.RANGE, "secondary")
    assert secondary.output(rate_hz=10, binary=True).text == "RANGEHB 0.1"
    assert LogEntry("GPGGA", Port.COM1, 0.1).rate_hz == 10
    assert LogEntry("OBSVBASEA", Port.COM1, Trigger.ON_CHANGED).rate_hz is None
    plan = subscription_plan(
        [AntennaLog(Log.OBSVBASE, Log.OBSVBASE)], interval=1, binary=True
    )
    assert plan[0][1].text == "OBSVBASEB ONCHANGED"


def test_receiver_configures_multiple_families_and_verifies_selected_port() -> None:
    transport = SubscriptionTransport()
    transport.subscriptions[("GPGGA", Port.COM1)] = 1
    with Receiver(transport) as receiver:
        responses = receiver.set_output_rate(
            [Log.GPGGA, Log.BESTNAV, antenna_log(Log.RANGE, "secondary"), Log.RTCM1074],
            10,
            port=Port.COM2,
            verify=True,
        )
        assert all(item.accepted for item in responses)
        assert transport.subscriptions == {
            ("GPGGA", Port.COM1): 1,
            ("GPGGA", Port.COM2): 0.1,
            ("BESTNAVB", Port.COM2): 0.1,
            ("RANGEHB", Port.COM2): 0.1,
            ("RTCM1074", Port.COM2): 0.1,
        }
        assert transport.writes[-1] == b"LOGLISTA\r\n"


def test_receiver_validates_entire_batch_before_sending() -> None:
    transport = SubscriptionTransport()
    with Receiver(transport) as receiver:
        with pytest.raises(ValueError, match="ONCHANGED"):
            receiver.set_output_rate([Log.GPGGA, Log.OBSVBASE], 10)
        with pytest.raises(ValueError, match="distinct wire"):
            receiver.set_output_rate(
                [Log.BESTNAV, AntennaLog(Log.BESTPOS, Log.BESTNAV)], 10
            )
        with pytest.raises(ValueError, match="explicit receiver port"):
            receiver.set_output_rate(Log.GPGGA, 10, verify=True)
        with pytest.raises(ValueError, match="rate_hz"):
            receiver.set_output_rate(Log.GPGGA, 100)
        with pytest.raises(ValueError, match="one-shot"):
            receiver.set_output_rate(Log.UNILOGLIST, 1)
    assert transport.writes == []


def test_batch_failure_reports_prior_changes_and_preserves_rejection() -> None:
    transport = SubscriptionTransport()
    transport.rejected.add("BESTNAVB COM1 0.1")
    with Receiver(transport) as receiver, pytest.raises(CommandRejected) as caught:
        receiver.set_output_rate(
            [Log.GPGGA, Log.BESTNAV, Log.RANGE], 10, port=Port.COM1
        )
    assert ("GPGGA", Port.COM1) in transport.subscriptions
    assert ("RANGEB", Port.COM1) not in transport.subscriptions
    assert "GPGGA COM1 0.1" in caught.value.__notes__[0]


def test_verify_detects_receiver_readback_mismatch() -> None:
    class WrongRate(SubscriptionTransport):
        def write(self, data: bytes, timeout: float) -> None:
            super().write(data, timeout)
            if data == b"GPGGA COM1 0.1\r\n":
                self.subscriptions[("GPGGA", Port.COM1)] = 1

    transport = WrongRate()
    with (
        Receiver(transport) as receiver,
        pytest.raises(ProtocolError, match="LOGLIST did not confirm"),
    ):
        receiver.set_output_rate(Log.GPGGA, 10, port=Port.COM1, verify=True)
    assert transport.subscriptions[("GPGGA", Port.COM1)] == 1


def test_async_rate_uses_same_receiver_and_readback() -> None:
    async def run() -> None:
        transport = SubscriptionTransport()
        async with AsyncReceiver(Receiver(transport)) as receiver:
            await receiver.set_output_rate(Log.GPGGA, 20, port=Port.COM1, verify=True)
            assert transport.subscriptions[("GPGGA", Port.COM1)] == 0.05
        assert transport.closed

    asyncio.run(run())


def test_stream_and_rover_configure_without_competing_for_receiver() -> None:
    transport = SubscriptionTransport()
    receiver = Receiver(transport, timeout=1)
    with ReceiverStream(receiver) as stream:
        responses = stream.set_output_rate(
            Log.GPGGA, 10, port=Port.COM1, verify=True
        ).result(timeout=3)
        assert responses[0].accepted
        assert transport.subscriptions[("GPGGA", Port.COM1)] == 0.1
    with Rover(receiver) as rover:
        responses = rover.set_output_rate(Log.GPGGA, 20, port=Port.COM1, verify=True)
        assert responses[0].accepted
        assert transport.subscriptions[("GPGGA", Port.COM1)] == 0.05
    assert not transport.closed
    receiver.close()


def test_cli_configures_and_checks_selected_receiver_port(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    transport = SubscriptionTransport()
    with patch.object(Receiver, "connect", return_value=Receiver(transport)):
        assert (
            main(
                [
                    "output-rate",
                    "--log",
                    "GPGGA",
                    "--log",
                    "BESTNAV",
                    "--rate-hz",
                    "10",
                    "--output-port",
                    "COM2",
                    "--verify-rate",
                ]
            )
            == 0
        )
    assert transport.subscriptions[("GPGGA", Port.COM2)] == 0.1
    assert transport.subscriptions[("BESTNAVA", Port.COM2)] == 0.1
    result = json.loads(capsys.readouterr().out)
    assert result["readback_verified"] is True
    assert result["actual_rate_measured"] is False


def test_cli_rejects_unsupported_rate_before_connecting() -> None:
    with patch.object(Receiver, "connect") as connect, pytest.raises(SystemExit):
        main(["output-rate", "--log", "GPGGA", "--rate-hz", "100"])
    connect.assert_not_called()


def test_cli_reports_partial_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    transport = SubscriptionTransport()
    transport.rejected.add("BESTNAVA 0.1")
    with patch.object(Receiver, "connect", return_value=Receiver(transport)):
        assert (
            main(
                ["output-rate", "--log", "GPGGA", "--log", "BESTNAV", "--rate-hz", "10"]
            )
            == 2
        )
    assert "GPGGA 0.1" in capsys.readouterr().err


def test_capture_uses_requested_rate_and_restores_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    frame = (Path(__file__).parent / "fixtures/captures/RANGEB.bin").read_bytes()

    class Transport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += min(0.1, timeout)
                if ("RANGEB", Port.COM1) in self.subscriptions:
                    self.pending.extend(frame)
            return super().read(size, timeout)

    transport = Transport()
    transport.subscriptions[("RANGEB", Port.COM1)] = 1
    monkeypatch.setattr("um982py.capture.monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    with Receiver(transport, timeout=1) as receiver:
        records = capture_live(receiver, Log.RANGE, duration=1, rate_hz=10, frames=2)
        assert len(records) == 2
        assert transport.subscriptions[("RANGEB", Port.COM1)] == 1
        assert b"RANGEB 0.1\r\n" in transport.writes


def test_capture_rejects_conflicts_and_event_only_before_write() -> None:
    transport = SubscriptionTransport()
    with Receiver(transport) as receiver:
        with pytest.raises(ValueError, match="interval or rate_hz"):
            capture_live(receiver, Log.RANGE, duration=1, interval=1, rate_hz=10)
        with pytest.raises(ValueError, match="ONCHANGED-only"):
            capture_live(receiver, [Log.RANGE, Log.OBSVBASE], duration=1, rate_hz=10)
        with pytest.raises(ValueError, match="rate_hz"):
            next(iter_live_records(receiver, [Log.RANGE], duration=1, rate_hz=100))
        with pytest.raises(ValueError, match="ONCHANGED-only"):
            next(iter_live_records(receiver, [Log.OBSVBASE], duration=1, rate_hz=10))
    assert transport.writes == []


def test_capture_plan_supports_independent_log_intervals() -> None:
    secondary = antenna_log(Log.RANGE, "secondary")
    plan = subscription_plan(
        [Log.RANGE, secondary, Log.JAMSTATUS, Log.OBSVBASE],
        interval=0.05,
        binary=True,
        intervals={secondary: 0.1, Log.JAMSTATUS: 1},
    )
    assert [command.text for _, command in plan] == [
        "RANGEB 0.05",
        "RANGEHB 0.1",
        "JAMSTATUSB 1",
        "OBSVBASEB ONCHANGED",
    ]


@pytest.mark.parametrize(
    "intervals",
    [
        {Log.JAMSTATUS: 0},
        {Log.JAMSTATUS: -1},
        {Log.JAMSTATUS: float("nan")},
        {Log.JAMSTATUS: float("inf")},
        {Log.JAMSTATUS: True},
        {Log.JAMSTATUS: 0.1},
        {Log.GPGGA: 1},
        {"JAMSTATUS": 1},
        {Log.OBSVBASE: 1},
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_invalid_capture_intervals_do_not_write(
    intervals: dict[Log, float], *, stream: bool
) -> None:
    transport = SubscriptionTransport()
    with Receiver(transport) as receiver, pytest.raises(ValueError):
        if stream:
            next(
                iter_live_records(
                    receiver,
                    [Log.RANGE, Log.JAMSTATUS, Log.OBSVBASE],
                    duration=1,
                    intervals=intervals,
                )
            )
        else:
            capture_live(
                receiver,
                [Log.RANGE, Log.JAMSTATUS, Log.OBSVBASE],
                duration=1,
                intervals=intervals,
            )
    assert transport.writes == []


@pytest.mark.parametrize("stream", [False, True])
def test_mixed_capture_intervals_restore_previous_subscriptions(
    *, stream: bool
) -> None:
    frame = Path("tests/fixtures/captures/RANGEB.bin").read_bytes()

    class StreamingTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending and ("RANGEB", Port.COM1) in self.subscriptions:
                assert self.subscriptions[("RANGEB", Port.COM1)] == 0.05
                assert self.subscriptions[("JAMSTATUSB", Port.COM1)] == 1
                self.pending.extend(frame)
            return super().read(size, timeout)

    transport = StreamingTransport()
    transport.subscriptions[("JAMSTATUSB", Port.COM1)] = 5
    original = dict(transport.subscriptions)
    with Receiver(transport) as receiver:
        if stream:
            records = iter_live_records(
                receiver,
                [Log.RANGE, Log.JAMSTATUS],
                duration=1,
                rate_hz=20,
                intervals={Log.JAMSTATUS: 1},
            )
            assert next(records)[0] == "RANGE"
            records.close()
        else:
            with patch("um982py.capture.receive_records", return_value={}) as receive:
                capture_live(
                    receiver,
                    [Log.RANGE, Log.JAMSTATUS],
                    duration=1,
                    rate_hz=20,
                    intervals={Log.JAMSTATUS: 1},
                )
                receive.assert_called_once()
            assert b"RANGEB 0.05\r\n" in transport.writes
            assert b"JAMSTATUSB 1\r\n" in transport.writes
        assert transport.subscriptions == original
