"""Checks the capture contracts shared by the runnable examples."""

import argparse
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from conftest import SubscriptionTransport, ascii_message
from test_protocol import binary
from um982py import Receiver
from um982py import capture as _capture
from um982py.capture import (
    InterruptedCapture,
    capture_records,
    gps_signals,
    open_receiver,
    read_frames,
    receive_records,
    record_epoch,
    uniform_interval,
)
from um982py.commands.types import Port
from um982py.console import ExampleParser, add_receiver_arguments, write_json
from um982py.corrections import stale_correction
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.messages import Record


def options(**values: object) -> argparse.Namespace:
    return argparse.Namespace(replay=None, timeout=1.0, **values)


def test_shared_receiver_accepts_tcp_target() -> None:
    transport = SubscriptionTransport()
    with (
        patch.object(Receiver, "connect", return_value=Receiver(transport)) as factory,
        patch("um982py.capture.enable_augmentation") as augmentation,
    ):
        augmentation.return_value.changed = False
        augmentation.return_value.rejected = ()
        with open_receiver(
            options(port="tcp://127.0.0.1:4001", baud=921600, record=None)
        ):
            pass
    factory.assert_called_once_with("tcp://127.0.0.1:4001", 921600, timeout=1.0)
    augmentation.assert_not_called()
    assert transport.closed


def test_shared_receiver_augmentation_is_explicit() -> None:
    receiver = Mock()
    with (
        patch.object(Receiver, "connect", return_value=receiver),
        patch("um982py.capture.enable_augmentation") as augmentation,
    ):
        augmentation.return_value.changed = False
        augmentation.return_value.rejected = ()
        open_receiver(options(port="fake", baud=921600, record=None, augment=True))
    augmentation.assert_called_once_with(receiver)


def test_old_rtcm_does_not_count_as_a_current_fixed_solution() -> None:
    assert stale_correction("NARROW_INT", 419.0)
    assert stale_correction(50, 11.0)
    assert not stale_correction("NARROW_INT", 2.0)
    assert not stale_correction("SINGLE", 419.0)
    assert not stale_correction("PPP", 419.0)


@pytest.mark.parametrize("service", ["AUTO", "E6-HAS", "B2B-PPP"])
def test_live_receiver_configures_requested_ppp_service(service: str) -> None:
    receiver = Mock()
    with (
        patch.object(Receiver, "connect", return_value=receiver),
        patch("um982py.capture.enable_augmentation") as augmentation,
    ):
        augmentation.return_value.changed = False
        augmentation.return_value.rejected = ()
        result = open_receiver(
            options(
                port="fake",
                baud=921600,
                record=None,
                ppp_service=service,
            )
        )
    assert result is receiver
    assert [call.args[0].text for call in receiver.execute.call_args_list] == [
        f"CONFIG PPP ENABLE {service}",
        "CONFIG PPP DATUM WGS84",
    ]


def test_live_collection_waits_for_multiple_epochs_and_restores_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    frame = binary((0).to_bytes(4, "little"), 43)

    class StreamingTransport(SubscriptionTransport):
        emitted = 0

        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += min(1.0, timeout)
                if ("RANGEB", Port.COM1) in self.subscriptions:
                    self.pending.extend(frame)
                    self.emitted += 1
            return super().read(size, timeout)

    transport = StreamingTransport()
    monkeypatch.setattr(_capture, "monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        _capture, "open_receiver", lambda args: Receiver(transport, timeout=1.0)
    )
    snapshots: list[dict[str, tuple[Record, ...]]] = []
    records = capture_records(
        options(), [FirmwareLog.RANGE], frames=3, on_progress=snapshots.append
    )["RANGE"]
    assert len(records) == 3
    assert transport.emitted == 3
    assert clock[0] == pytest.approx(3.0)
    assert transport.subscriptions == {}
    assert transport.closed
    assert len(snapshots[-1]["RANGE"]) == 3


def test_replay_decodes_ascii_and_binary_without_opening_a_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mixed.bin"
    path.write_bytes(
        ascii_message("RANGEA", "0") + binary((0).to_bytes(4, "little"), 43)
    )

    def unexpected_open(args: argparse.Namespace) -> Receiver:
        pytest.fail("replay must not open a live receiver")

    monkeypatch.setattr(_capture, "open_receiver", unexpected_open)
    snapshots: list[dict[str, tuple[Record, ...]]] = []
    result = capture_records(
        argparse.Namespace(replay=path),
        [FirmwareLog.RANGE],
        on_progress=snapshots.append,
    )["RANGE"]
    assert len(result) == 2
    assert snapshots[0]["RANGE"] == result
    assert [record.integer("count") for record in result] == [0, 0]


def test_cancelled_capture_restores_logs_and_preserves_received_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptedTransport(SubscriptionTransport):
        interrupted = False

        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            return super().read(size, timeout)

    transport = InterruptedTransport()
    transport.after_write["RANGEB 1"] = binary((0).to_bytes(4, "little"), 43)
    monkeypatch.setattr(_capture, "open_receiver", lambda args: Receiver(transport))
    result = capture_records(options(), [FirmwareLog.RANGE], frames=3)
    assert len(result["RANGE"]) == 1
    assert not transport.subscriptions
    assert transport.closed


def test_cancelled_sweep_reader_propagates_cancellation() -> None:
    class InterruptedTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            raise KeyboardInterrupt

    with (
        Receiver(InterruptedTransport()) as receiver,
        pytest.raises(InterruptedCapture) as caught,
    ):
        receive_records(receiver, [FirmwareLog.RANGE], duration=1.0)
    assert caught.value.records == {"RANGE": ()}


def test_truncated_capture_is_reported_instead_of_silently_accepted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "truncated.bin"
    path.write_bytes(binary((0).to_bytes(4, "little"), 43)[:-2])
    with pytest.raises(ProtocolError, match="Incomplete frame"):
        read_frames(path)


def test_incremental_frame_reader_handles_boundaries_and_truncation(
    tmp_path: Path,
) -> None:
    from um982py.capture import iter_frames

    first, second = binary(b"first", 43), binary(b"second", 43)
    path = tmp_path / "frames.bin"
    path.write_bytes(first + second)
    assert [message.raw for message in iter_frames(path, chunk_size=7)] == [
        first,
        second,
    ]
    path.write_bytes(first + second[:-1])
    with pytest.raises(ProtocolError, match="Incomplete frame"):
        tuple(iter_frames(path, chunk_size=7))
    with pytest.raises(ValueError, match="positive"):
        tuple(iter_frames(path, chunk_size=0))


def test_raw_recording_survives_reconnect_and_refuses_existing_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capture.bin"
    args = argparse.Namespace(
        port="fake", baud=921600, timeout=1.0, replay=None, record=path
    )
    transports = [SubscriptionTransport(), SubscriptionTransport()]
    for transport in transports:
        transport.pending.extend(b"captured\r\n")
    with patch.object(
        Receiver, "serial", side_effect=[Receiver(t) for t in transports]
    ):
        for _ in transports:
            with open_receiver(args) as receiver:
                assert receiver.transport.read(65536, 1.0) == b"captured\r\n"
    assert path.read_bytes() == b"captured\r\ncaptured\r\n"
    assert all(transport.closed for transport in transports)
    fresh_args = argparse.Namespace(port="fake", baud=921600, replay=None, record=path)
    transport = SubscriptionTransport()
    with (
        patch.object(Receiver, "serial", return_value=Receiver(transport)),
        pytest.raises(FileExistsError),
    ):
        open_receiver(fresh_args)
    assert transport.closed
    assert path.read_bytes() == b"captured\r\ncaptured\r\n"


def test_json_output_creates_directories_and_uses_null_for_missing_numbers(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "reports" / "result.json"
    write_json({"sigma": float("nan"), "values": [float("inf"), 1]}, destination)
    assert json.loads(destination.read_text()) == {"sigma": None, "values": [None, 1]}


@pytest.mark.parametrize(
    "arguments",
    [
        ["--timeout", "nan"],
        ["--timeout", "0"],
        ["--replay", "data.bin", "--port", "fake"],
        ["--record", "data.bin", "--json", "data.bin"],
        ["--replay", "data.bin", "--json", "data.bin"],
    ],
)
def test_invalid_shared_arguments_fail_before_io(arguments: list[str]) -> None:
    parser = ExampleParser()
    add_receiver_arguments(parser)
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(arguments)
    assert caught.value.code == 2


def test_gps_selection_uses_system_signal_and_validity_bits() -> None:
    def observation(status: int, cn0: float) -> Record:
        return Record(
            "observation", (("prn", 7), ("tracking_status", status), ("cn0", cn0))
        )

    valid = (1 << 10) | (1 << 12)
    selected = observation(valid, 35.0)
    record = Record(
        "RANGE",
        (
            (
                "observations",
                (
                    selected,
                    observation(valid | (4 << 16), 50),
                    observation(valid | (14 << 21), 45),
                    observation(0, 60),
                ),
            ),
        ),
    )
    assert gps_signals(record, [1575.42e6]) == ((selected, 1575.42e6),)


def test_uniform_sampling_checks_actual_receiver_timestamps() -> None:
    from dataclasses import replace

    from um982py.messages import BinaryMessage
    from um982py.protocol import StreamDecoder

    message = StreamDecoder().feed(binary((0).to_bytes(4, "little"), 43))[0]
    assert isinstance(message, BinaryMessage)
    first = FirmwareLog.RANGE.decode(message)
    assert record_epoch(first) == 2400 * 604800 + 123
    header = message.header
    second = FirmwareLog.RANGE.decode(
        replace(message, header=replace(header, milliseconds=125000))
    )
    assert uniform_interval([first, second], 1.0) == 2.0
    with pytest.raises(ValueError, match="irregular"):
        uniform_interval([first, second, second], 1.0)


def test_library_capture_uses_open_receiver_without_cli_or_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = [0.0]
    frame = binary((0).to_bytes(4, "little"), 43)

    class StreamingTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += min(1.0, timeout)
                if ("RANGEB", Port.COM1) in self.subscriptions:
                    self.pending.extend(frame)
            return super().read(size, timeout)

    transport = StreamingTransport()
    monkeypatch.setattr(_capture, "monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    receiver = Receiver(transport, timeout=1.0)
    records = _capture.capture_live(receiver, [FirmwareLog.RANGE], duration=8, frames=3)
    assert len(records["RANGE"]) == 3
    assert transport.subscriptions == {}
    assert not transport.closed
    assert capsys.readouterr().err == ""
    receiver.close()
