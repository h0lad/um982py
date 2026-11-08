import json
from pathlib import Path
from threading import Event

import pytest

from conftest import ReplayTransport, sentence
from um982py.capture import RecordingTransport
from um982py.errors import ProtocolError, RecordingError, TransportClosed
from um982py.live import PositionSession
from um982py.ntrip import ReconnectPolicy
from um982py.receiver import Receiver
from um982py.session import (
    SessionGap,
    SessionRecorder,
    iter_session_bytes,
    iter_session_events,
    iter_session_frames,
)


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


def test_incomplete_replay_ignores_torn_final_journal_entry(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    with SessionRecorder(directory, metadata={}, segment_bytes=3) as recorder:
        recorder.write(b"abc")
    journal = directory / "segments.jsonl"
    completed = journal.read_text().splitlines()[0]
    journal.write_text(completed + '\n{"gap":')
    with pytest.raises(ValueError, match="incomplete entry"):
        list(iter_session_bytes(directory))
    assert b"".join(iter_session_bytes(directory, allow_incomplete=True)) == b"abc"


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
    with pytest.raises(RecordingError, match="short write"):
        transport.read(3, 1)


def test_session_never_overwrites_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError):
        SessionRecorder(tmp_path, metadata={})


@pytest.mark.parametrize("size", [0, -1, True, 1.5])
def test_segment_size_is_positive_integer(tmp_path: Path, size: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        SessionRecorder(tmp_path, metadata={}, segment_bytes=size)  # type: ignore[arg-type]


def test_reconnect_records_gap_and_replay_does_not_join_partial_frames(
    tmp_path: Path,
) -> None:
    class Connection(ReplayTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                raise TransportClosed("receiver disconnected")
            return super().read(size, timeout)

    def gga(quality: int) -> bytes:
        return sentence(
            f"GPGGA,123519,4807.038,N,01131.000,E,{quality},08,0.9,545.4,M,46.9,M,1.2,0001".encode()
        )

    first, second = Connection(chunk=65536), Connection(chunk=65536)
    partial = b"$GPGGA,partial"
    first.pending.extend(gga(4) + partial)
    second.pending.extend(gga(5))
    sources = iter((first, second))
    directory = tmp_path / "session"
    with SessionRecorder(directory, metadata={}, segment_bytes=1024) as recorder:

        def connect() -> Receiver:
            return Receiver(
                RecordingTransport(next(sources), recorder, close_stream=False)
            )

        session = PositionSession(
            connect,
            on_disconnect=lambda error: recorder.mark_gap(str(error)),
            reconnect=ReconnectPolicy(0.001, 0.001),
        )
        positions = session.positions(Event())
        assert next(positions).fix.quality == 4
        assert next(positions).fix.quality == 5
        positions.close()

    events = list(iter_session_events(directory))
    assert len(events) == 3 and isinstance(events[1], SessionGap)
    assert events[1].reason == "receiver disconnected"
    assert events[1].pending_bytes == len(partial)
    assert events[0].raw == gga(4) and events[2].raw == gga(5)
    with pytest.raises(ProtocolError, match="contains a gap"):
        list(iter_session_frames(directory))
    assert b"".join(iter_session_bytes(directory)) == gga(4) + partial + gga(5)


def test_storage_error_stops_position_session_instead_of_reconnecting() -> None:
    class FullSink:
        def write(self, data: bytes) -> int:
            raise OSError("disk full")

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    transport = ReplayTransport()
    transport.pending.extend(sentence(b"GPGGA,1"))
    session = PositionSession(
        lambda: Receiver(RecordingTransport(transport, FullSink()))
    )
    with pytest.raises(RecordingError, match="disk full"):
        next(session.positions(Event()))
    assert session.health().state == "failed" and session.health().attempts == 1
