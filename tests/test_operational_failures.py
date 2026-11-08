from io import BytesIO
from pathlib import Path

import pytest

from conftest import ReplayTransport, sentence
from um982py.capture import RecordingTransport, iter_frames
from um982py.errors import ProtocolError, RecordingError


def test_recording_surfaces_storage_failure() -> None:
    class FullDisk(BytesIO):
        def write(self, data: bytes) -> int:
            raise OSError("disk full")

    transport = ReplayTransport()
    transport.pending.extend(sentence(b"GPGGA,1"))
    recording = RecordingTransport(transport, FullDisk())
    with pytest.raises(RecordingError, match="disk full"):
        recording.read(100, 1)
    recording.close()
    assert transport.closed


def test_replay_rejects_truncated_capture(tmp_path: Path) -> None:
    capture = tmp_path / "incomplete.bin"
    capture.write_bytes(sentence(b"GPGGA,1")[:-3])
    with pytest.raises(ProtocolError):
        list(iter_frames(capture))
