"""Test raw session recording and its offline audit."""

import json
from pathlib import Path

import pytest
from tools.test_data_recorder import audit, profile, record

from conftest import SubscriptionTransport
from test_protocol import binary
from um982py.commands import Port
from um982py.errors import CommandRejected, TransportError
from um982py.session import SessionRecorder, iter_session_bytes

FIXTURES = Path(__file__).parent / "fixtures"


class Input:
    def __init__(self, chunks: list[bytes | BaseException]) -> None:
        self.chunks = iter(chunks)
        self.time = 0.0
        self.closed = False

    def read(self, size: int, timeout: float) -> bytes:
        self.time += 1
        value = next(self.chunks, b"")
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


def test_record_preserves_raw_bytes_across_segments_and_audits(tmp_path: Path) -> None:
    raw = (FIXTURES / "bodies/OBSVHB.bin").read_bytes()
    position = (
        (FIXTURES / "captures-live/BESTNAVA.bin")
        .read_bytes()
        .splitlines(keepends=True)[0]
    )
    payload = raw + position + b"$GPGGA,1*00\r\n" + b"\xaa\x44"
    source = Input([payload[:10], payload[10:]])
    directory = tmp_path / "session"
    with SessionRecorder(directory, segment_bytes=37) as recorder:
        report = record.record(
            source,
            recorder,
            2,
            clock=lambda: source.time,  # type: ignore[arg-type]
        )
    assert report["status"] == "complete"
    assert report["received_bytes"] == len(payload)
    assert b"".join(iter_session_bytes(directory)) == payload
    assert len(list(directory.glob("segment-*.bin"))) > 1
    result = audit.audit(directory)
    assert result["valid_frames"]["OBSVH"] == 1
    assert result["other_frames"] == 1
    assert result["decoder_errors_at_least"] >= 1
    assert result["pending_bytes"] == 2
    assert result["received_bytes"] == len(payload)
    exported = tmp_path / "capture.bin"
    assert audit.main([str(directory), "--export", str(exported)]) == 0
    assert exported.read_bytes() == payload
    with pytest.raises(FileExistsError):
        audit.main([str(directory), "--export", str(exported)])


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (KeyboardInterrupt(), "interrupted"),
        (TransportError("disconnected"), "transport_error"),
    ],
)
def test_record_preserves_partial_capture_on_interruption(
    tmp_path: Path, failure: BaseException, status: str
) -> None:
    source = Input([b"first chunk", failure])
    directory = tmp_path / "session"
    with SessionRecorder(directory) as recorder:
        report = record.record(
            source,
            recorder,
            3,
            clock=lambda: source.time,  # type: ignore[arg-type]
        )
    assert report["status"] == status
    assert b"".join(iter_session_bytes(directory)) == b"first chunk"
    if status == "transport_error":
        with pytest.raises(ValueError, match="gap"):
            audit.audit(directory)


def test_cli_writes_metadata_and_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SubscriptionTransport()
    source.subscriptions = {("OBSVMB", Port.COM1): 5.0, ("RANGEB", Port.COM2): 2.0}
    original = dict(source.subscriptions)
    monkeypatch.setattr(record, "SerialTransport", lambda *args: source)

    def capture(
        transport: object, recorder: SessionRecorder, duration: float, **kwargs: object
    ) -> dict:
        assert source.subscriptions[("OBSVMB", Port.COM1)] == 1.0
        assert source.subscriptions[("OBSVHB", Port.COM1)] == 1.0
        assert source.subscriptions[("OBSVMCMPB", Port.COM1)] == 1.0
        assert ("E6MASKBLOCKB", Port.COM1) in source.subscriptions
        recorder.write(b"original data")
        return {"status": "complete", "received_bytes": len(b"original data")}

    monkeypatch.setattr(
        record,
        "record",
        capture,
    )
    notes = tmp_path / "metadata.json"
    notes.write_text('{"antenna": "TEST"}')
    output = tmp_path / "session"
    args = [
        "dummy",
        str(output),
        "--receiver-port",
        "COM1",
        "--duration",
        "1",
        "--metadata",
        str(notes),
        "--compressed",
        "--corrections",
    ]
    assert record.main(args) == 0
    assert source.closed
    assert b"original data" in b"".join(iter_session_bytes(output))
    assert source.subscriptions == original
    assert json.loads((output / "session.json").read_text())["metadata"]["notes"] == {
        "antenna": "TEST"
    }
    assert json.loads((output / "capture.json").read_text())["status"] == "complete"
    assert json.loads((output / "capture.json").read_text())["subscriptions_restored"]
    with pytest.raises(FileExistsError):
        record.main(args)


@pytest.mark.parametrize("status_format", ["text", "json"])
def test_cli_status_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status_format: str,
) -> None:
    source = SubscriptionTransport()
    monkeypatch.setattr(record, "SerialTransport", lambda *args: source)

    def capture(
        transport: object, recorder: SessionRecorder, duration: float, **kwargs: object
    ) -> dict:
        values = {
            "elapsed_seconds": 1,
            "requested_seconds": duration,
            "window_seconds": 1,
            "received_bytes": 0,
            "average_bytes_per_second": 0,
            "recent_bytes_per_second": 0,
            "data_age_seconds": None,
            "valid_frames": dict.fromkeys((log.value for log in audit.LOGS), 0),
            "recent_frames": dict.fromkeys((log.value for log in audit.LOGS), 0),
            "observation_age_seconds": {"OBSVM": None, "OBSVH": None},
            "other_frames": 0,
            "decoder_errors_at_least": 0,
            "discarded_bytes": 0,
            "pending_bytes": 0,
        }
        kwargs["progress"](values)  # type: ignore[operator]
        return {"status": "complete", "received_bytes": 0}

    monkeypatch.setattr(record, "record", capture)
    assert (
        record.main(
            [
                "dummy",
                str(tmp_path / "session"),
                "--receiver-port",
                "COM1",
                "--duration",
                "10",
                "--status-format",
                status_format,
            ]
        )
        == 0
    )
    output = capsys.readouterr().err
    if status_format == "json":
        values = json.loads(
            next(line for line in output.splitlines() if line.startswith("{"))
        )
        assert values["elapsed_seconds"] == 1
        assert values["free_disk_bytes"] >= 0
    else:
        assert "[00:00:01 / 00:00:10] 10.0%" in output
        assert "ANT2 OBSVH: 0 (+0), not received" in output


def test_configuration_failure_restores_previous_subscriptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SubscriptionTransport()
    source.subscriptions = {("OBSVMB", Port.COM1): 5.0, ("RANGEB", Port.COM2): 2.0}
    original = dict(source.subscriptions)
    source.rejected.add("OBSVHB COM1 1")
    monkeypatch.setattr(record, "SerialTransport", lambda *args: source)
    with pytest.raises(CommandRejected):
        record.main(["dummy", str(tmp_path / "session"), "--receiver-port", "COM1"])
    assert source.subscriptions == original
    assert source.closed


def test_restoration_failure_preserves_recording_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DisconnectedOnRestore(SubscriptionTransport):
        def write(self, data: bytes, timeout: float) -> None:
            if data.startswith(b"UNLOG "):
                raise TransportError("disconnected")
            super().write(data, timeout)

    source = DisconnectedOnRestore()
    monkeypatch.setattr(record, "SerialTransport", lambda *args: source)

    def capture(
        transport: object, recorder: SessionRecorder, duration: float, **kwargs: object
    ) -> dict:
        recorder.write(b"original data")
        return {"status": "complete", "received_bytes": len(b"original data")}

    monkeypatch.setattr(record, "record", capture)
    directory = tmp_path / "session"
    with pytest.raises(ExceptionGroup, match="restore"):
        record.main(["dummy", str(directory), "--receiver-port", "COM1"])
    report = json.loads((directory / "capture.json").read_text())
    assert report["status"] == "complete"
    assert report["subscriptions_restored"] is False
    assert b"original data" in b"".join(iter_session_bytes(directory))


def test_audit_rejects_corrupted_segment(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    with SessionRecorder(directory) as recorder:
        recorder.write(b"original")
    (directory / "segment-000001.bin").write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.audit(directory)
    exported = tmp_path / "capture.bin"
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.main([str(directory), "--export", str(exported)])
    assert not exported.exists()


def test_empty_stream_is_not_reported_as_success(tmp_path: Path) -> None:
    source = Input([])
    with SessionRecorder(tmp_path / "session") as recorder:
        report = record.record(
            source,
            recorder,
            1,
            clock=lambda: source.time,  # type: ignore[arg-type]
        )
    assert report["status"] == "no_data"


def test_timed_segments_and_status_track_both_antennas(tmp_path: Path) -> None:
    primary = binary(b"\x00" * 4, message_id=12)
    secondary = binary(b"\x00" * 4, message_id=13)
    source = Input([primary, secondary, b"", primary])
    directory = tmp_path / "session"
    updates: list[dict] = []
    with SessionRecorder(directory, segment_bytes=10000) as recorder:
        report = record.record(
            source,  # type: ignore[arg-type]
            recorder,
            4,
            segment_seconds=2,
            status_seconds=2,
            progress=updates.append,
            clock=lambda: source.time,
        )
    assert b"".join(iter_session_bytes(directory)) == primary + secondary + primary
    assert len(list(directory.glob("segment-*.bin"))) == 2
    assert updates[0]["valid_frames"]["OBSVM"] == 1
    assert updates[0]["valid_frames"]["OBSVH"] == 1
    assert updates[0]["recent_frames"]["OBSVM"] == 1
    assert updates[0]["recent_frames"]["OBSVH"] == 1
    assert updates[0]["observation_age_seconds"] == {"OBSVM": 1.0, "OBSVH": 0.0}
    assert updates[1]["observation_age_seconds"]["OBSVH"] == 2.0
    assert updates[1]["recent_frames"]["OBSVM"] == 1
    assert updates[1]["recent_frames"]["OBSVH"] == 0
    assert updates[1]["window_seconds"] == 2
    assert report["valid_frames"]["OBSVM"] == 2


def test_status_shows_progress_and_missing_or_stale_antennas(tmp_path: Path) -> None:
    primary = binary(b"\x00" * 4, message_id=12)
    source = Input([primary])
    updates: list[dict] = []
    with SessionRecorder(tmp_path / "session") as recorder:
        record.record(
            source,  # type: ignore[arg-type]
            recorder,
            8,
            status_seconds=8,
            progress=updates.append,
            clock=lambda: source.time,
        )
    text = record.format_status(updates[0])
    assert "[00:00:08 / 00:00:08] 100.0%" in text
    assert "ANT1 OBSVM: 1 (+1), 7.0s ago, stale" in text
    assert "ANT2 OBSVH: 0 (+0), not received" in text
    assert "Ephemerides (total): GPSEPH=0" in text
    assert "free unknown" in text


def test_profile_commands_cover_both_antennas_and_optional_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert profile.main([]) == 0
    core = capsys.readouterr().out.splitlines()
    assert "RANGEB 1" in core and "RANGEHB 1" in core
    assert "BSLNENUHDB ONCHANGED" in core
    assert "SATVIS2B 10" in core and "RECTIMEB 1" in core
    assert "OBSVMCMPB 1" not in core
    assert profile.main(["--compressed", "--corrections", "--port", "COM1"]) == 0
    extended = capsys.readouterr().out.splitlines()
    assert "OBSVMCMPB COM1 1" in extended
    assert "PPPB2BINFO1B COM1 ONCHANGED" in extended
    assert "E6MASKBLOCKB COM1 ONCHANGED" in extended


def test_live_and_offline_counts_include_changed_only_and_compressed_logs(
    tmp_path: Path,
) -> None:
    assert len(audit.NAMES_BY_ID) == len(profile.TRACKED)
    raw = b"".join(
        binary(b"\x00" * 4, message_id=number) for number in (138, 139, 2302, 2319)
    )
    source = Input([raw])
    directory = tmp_path / "session"
    with SessionRecorder(directory) as recorder:
        report = record.record(
            source,
            recorder,
            1,
            clock=lambda: source.time,  # type: ignore[arg-type]
        )
    counts = audit.audit(directory)["valid_frames"]
    for name in ("OBSVMCMP", "OBSVHCMP", "PPPB2BINFO1", "E6MASKBLOCK"):
        assert counts[name] == report["valid_frames"][name] == 1
