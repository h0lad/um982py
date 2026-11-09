"""Test raw session recording and its offline audit."""

import json
from pathlib import Path

import pytest
from tools.test_data_recorder import audit, profile, record

from test_protocol import binary
from um982py.errors import TransportError
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
    source = Input([b"original data"])
    monkeypatch.setattr(record, "SerialTransport", lambda *args: source)
    run = record.record
    monkeypatch.setattr(
        record,
        "record",
        lambda transport, recorder, duration, **kwargs: run(
            transport, recorder, duration, clock=lambda: source.time, **kwargs
        ),
    )
    notes = tmp_path / "metadata.json"
    notes.write_text('{"antenna": "TEST"}')
    output = tmp_path / "session"
    args = ["dummy", str(output), "--duration", "1", "--metadata", str(notes)]
    assert record.main(args) == 0
    assert source.closed
    assert b"".join(iter_session_bytes(output)) == b"original data"
    assert json.loads((output / "session.json").read_text())["metadata"]["notes"] == {
        "antenna": "TEST"
    }
    assert json.loads((output / "capture.json").read_text())["status"] == "complete"
    with pytest.raises(FileExistsError):
        record.main(args)


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
    assert updates[0]["observation_age_seconds"] == {"OBSVM": 1.0, "OBSVH": 0.0}
    assert updates[1]["observation_age_seconds"]["OBSVH"] == 2.0
    assert report["valid_frames"]["OBSVM"] == 2


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
