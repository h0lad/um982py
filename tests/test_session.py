import json
from pathlib import Path

import pytest

from conftest import ReplayTransport, sentence
from um982py.capture import RecordingTransport
from um982py.session import SessionRecorder, iter_session_bytes, iter_session_frames


def test_recording_transport_preserves_frames_across_segments(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    payload = sentence(b"GPGGA,1") + sentence(b"GPRMC,2")
    source = ReplayTransport({b"start": payload}, chunk=7)
    recorder = SessionRecorder(directory, metadata={"antenna": "test"}, segment_bytes=9)
    transport = RecordingTransport(source, recorder)
    transport.write(b"start", 1)
    while transport.read(1024, 1):
        pass
    transport.close()

    assert b"".join(iter_session_bytes(directory, chunk_size=4)) == payload
    assert [frame.raw for frame in iter_session_frames(directory)] == [
        sentence(b"GPGGA,1"),
        sentence(b"GPRMC,2"),
    ]
    manifest = json.loads((directory / "session.json").read_text())
    assert manifest["metadata"] == {"antenna": "test"}
    assert len(list(directory.glob("segment-*.bin"))) > 1


def test_incomplete_session_requires_explicit_opt_in(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    recorder = SessionRecorder(directory, metadata={}, segment_bytes=3)
    recorder.write(b"abcde")
    recorder.flush()
    with pytest.raises(ValueError, match="incomplete"):
        list(iter_session_bytes(directory))
    assert b"".join(iter_session_bytes(directory, allow_incomplete=True)) == b"abc"
    recorder.close()
    assert b"".join(iter_session_bytes(directory)) == b"abcde"


def test_replay_rejects_corrupted_segment(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    with SessionRecorder(directory, metadata={}, segment_bytes=10) as recorder:
        recorder.write(b"original")
    (directory / "segment-000001.bin").write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        list(iter_session_bytes(directory))


def test_recording_transport_rejects_short_sink_write() -> None:
    class ShortSink:
        def write(self, data: bytes) -> int:
            return len(data) - 1

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    source = ReplayTransport({b"start": b"abc"})
    transport = RecordingTransport(source, ShortSink())
    transport.write(b"start", 1)
    with pytest.raises(OSError, match="short write"):
        transport.read(3, 1)


def test_session_never_overwrites_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        SessionRecorder(tmp_path, metadata={})


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_segment_size_is_positive_integer(tmp_path: Path, size: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        SessionRecorder(tmp_path, metadata={}, segment_bytes=size)  # type: ignore[arg-type]
