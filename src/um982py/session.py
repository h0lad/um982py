"""Segment received bytes into an auditable, replayable field session."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from um982py.messages import Message
from um982py.protocol import StreamDecoder

if TYPE_CHECKING:
    from typing import BinaryIO


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionRecorder:
    """Write bounded raw segments through ``capture.RecordingTransport``.

    A new directory is required. Complete segments are journalled with hashes;
    an interrupted write leaves a ``.part`` file for inspection. Metadata is
    supplied by the caller and is not inferred from receiver messages.
    """

    def __init__(
        self,
        directory: Path,
        *,
        metadata: Mapping[str, object],
        segment_bytes: int = 64 * 1024 * 1024,
        fsync: bool = False,
    ) -> None:
        if (
            not isinstance(segment_bytes, int)
            or isinstance(segment_bytes, bool)
            or segment_bytes < 1
        ):
            raise ValueError("segment_bytes must be a positive integer")
        manifest = json.dumps(
            {
                "schema": "um982py-session-1",
                "started_at": _now(),
                "metadata": dict(metadata),
            },
            allow_nan=False,
            indent=2,
        )
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / "session.json").write_text(manifest + "\n", encoding="utf-8")
        self.segment_bytes = segment_bytes
        self.fsync = fsync
        self._journal = (self.directory / "segments.jsonl").open("x", encoding="utf-8")
        self._file: BinaryIO | None = None
        self._hash = hashlib.sha256()
        self._size = 0
        self._number = 0
        self._started = ""
        self._closed = False

    def _open_segment(self) -> BinaryIO:
        self._number += 1
        self._size = 0
        self._hash = hashlib.sha256()
        self._started = _now()
        self._file = (self.directory / f"segment-{self._number:06d}.part").open("xb")
        return self._file

    def _event(self, event: dict[str, object]) -> None:
        self._journal.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._journal.flush()
        if self.fsync:
            os.fsync(self._journal.fileno())

    def _finish_segment(self) -> None:
        if self._file is None:
            return
        self._file.flush()
        if self.fsync:
            os.fsync(self._file.fileno())
        self._file.close()
        self._file = None
        stem = f"segment-{self._number:06d}"
        (self.directory / f"{stem}.part").replace(self.directory / f"{stem}.bin")
        self._event(
            {
                "segment": f"{stem}.bin",
                "bytes": self._size,
                "sha256": self._hash.hexdigest(),
                "started_at": self._started,
                "ended_at": _now(),
            }
        )

    def write(self, data: bytes, /) -> int:
        if self._closed:
            raise ValueError("session is closed")
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            stream = self._file if self._file is not None else self._open_segment()
            chunk = view[offset : offset + self.segment_bytes - self._size]
            written = stream.write(chunk)
            if written != len(chunk):
                raise OSError("short write to session segment")
            self._hash.update(chunk)
            self._size += written
            offset += written
            if self._size == self.segment_bytes:
                self._finish_segment()
        return offset

    def flush(self) -> None:
        if self._closed:
            raise ValueError("session is closed")
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._finish_segment()
            self._event({"closed_at": _now()})
        finally:
            self._closed = True
            if self._file is not None:
                self._file.close()
            self._journal.close()

    def __enter__(self) -> SessionRecorder:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def iter_session_bytes(
    directory: Path, *, allow_incomplete: bool = False, chunk_size: int = 65536
) -> Iterator[bytes]:
    """Verify journalled segments and yield their bytes in capture order.

    In incomplete sessions, opt in to replay only the journalled segments;
    unfinished or unjournalled files are never silently included.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    directory = Path(directory)
    manifest = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != "um982py-session-1":
        raise ValueError("unsupported session manifest")
    journal = (directory / "segments.jsonl").read_text(encoding="utf-8")
    segments: list[tuple[Path, int, str]] = []
    closed = False
    for line in journal.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict) or closed:
            raise ValueError("invalid session journal")
        if "closed_at" in event:
            closed = True
            continue
        name = f"segment-{len(segments) + 1:06d}.bin"
        size = event.get("bytes")
        digest = event.get("sha256")
        if (
            event.get("segment") != name
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 1
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("invalid session segment entry")
        segments.append((directory / name, size, digest))
    if not allow_incomplete and (
        not closed
        or any(directory.glob("segment-*.part"))
        or {path.name for path in directory.glob("segment-*.bin")}
        != {path.name for path, _, _ in segments}
    ):
        raise ValueError("session is incomplete")
    for path, expected_size, expected_hash in segments:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(chunk_size):
                size += len(chunk)
                digest.update(chunk)
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise ValueError(f"session segment hash mismatch: {path.name}")
        with path.open("rb") as source:
            while chunk := source.read(chunk_size):
                yield chunk


def iter_session_frames(
    directory: Path, *, allow_incomplete: bool = False
) -> Iterator[Message]:
    """Decode the complete byte stream, including frames split across segments."""
    decoder = StreamDecoder(strict=True)
    for chunk in iter_session_bytes(directory, allow_incomplete=allow_incomplete):
        yield from decoder.feed(chunk)
    decoder.finish()
