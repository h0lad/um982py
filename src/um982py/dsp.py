"""DSP capture, wire framing and payload decoding."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from um982py.commands import Log
from um982py.commands.catalog import LOGS, RTCM_LOGS
from um982py.commands.core import Command
from um982py.errors import ProtocolError, UM982Error
from um982py.experimental import DebugOutput, FirmwareLog, log_list
from um982py.experimental.baseband import RawBasebandPacket, scan_packets
from um982py.experimental.capture import (
    CaptureAnalysis,
    RecordingTransport,
    analyze_capture,
    receiver_state,
)
from um982py.messages import (
    BinaryMessage,
    CommandResponse,
    Message,
)
from um982py.messages.decode import decode_log
from um982py.messages.record import Record, Value

if TYPE_CHECKING:
    from um982py.receiver import Receiver


class DspProfile(StrEnum):
    OBSERVATIONS = "observations"
    SAMPLES = "samples"
    BASEBAND = "baseband"
    BASEBAND_PERIODIC = "baseband-periodic"
    TRANSFER = "transfer"
    RAWDATA = "rawdata"
    TRACKING = "tracking"

    def subscriptions(
        self,
    ) -> tuple[tuple[str, Command[CommandResponse], Command[CommandResponse]], ...]:
        if self == self.OBSERVATIONS:
            return tuple(
                (
                    log.wire_name(binary=True),
                    log.output(0.2, binary=True),
                    log.stop(binary=True),
                )
                for log in (Log.OBSVM, Log.OBSVH)
            )
        if self == self.TRACKING:
            log = FirmwareLog.PTOBSINFO
            return (
                (
                    log.wire_name(binary=True),
                    log.output(1, binary=True),
                    log.stop(binary=True),
                ),
            )
        outputs = {
            self.SAMPLES: (DebugOutput.SAMPLE_DATA,),
            self.BASEBAND: (DebugOutput.BASEBAND_PACKETS,),
            self.BASEBAND_PERIODIC: (DebugOutput.BASEBAND_PACKETS,),
            self.TRANSFER: (DebugOutput.BASEBAND_TRANSFER,),
            self.RAWDATA: (DebugOutput.RAWDATA, DebugOutput.RAWDATA_SECONDARY),
        }[self]
        return tuple(
            (
                log.value,
                log.on_changed() if self == self.BASEBAND else log.output(1),
                log.stop(),
            )
            for log in outputs
        )


def decode_dsp(message: Message) -> Record:
    """Decode a framed payload, preserving unhandled bytes as opaque."""
    if isinstance(message, BinaryMessage):
        identifier = message.header.message_id
        matches_id = (
            d.message_id == identifier
            for name, d in LOGS.items()
            if name not in RTCM_LOGS
        )
        if any(matches_id):
            return decode_log(message)
        for log in FirmwareLog:
            if log == FirmwareLog.RXSTATUS:
                continue
            if log.request(binary=True).matches(message):
                return log.decode(message)
        return Record(
            "OPAQUE",
            (("message_id", identifier), ("payload", message.payload)),
            message,
        )
    for log in FirmwareLog:
        if log.request().matches(message):
            return log.decode(message)
    return decode_log(message)


def _value(value: Value) -> object:
    if isinstance(value, Record):
        return {key: _value(item) for key, item in value.entries}
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


@dataclass(frozen=True, slots=True)
class DspFrame:
    wire_offset: int
    payload_offset: int
    message: BinaryMessage
    record: Record | None
    error: str | None
    baseband: tuple[RawBasebandPacket, ...] = ()

    def manifest(self) -> dict[str, object]:
        return {
            "message_id": self.message.header.message_id,
            "header": asdict(self.message.header),
            "wire_offset": self.wire_offset,
            "wire_bytes": len(self.message.raw),
            "payload_offset": self.payload_offset,
            "payload_bytes": len(self.message.payload),
            "payload_sha256": sha256(self.message.payload).hexdigest(),
            "name": self.record.name if self.record else None,
            "fields": _value(self.record) if self.record else None,
            "baseband": [packet.manifest() for packet in self.baseband],
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DspCapture:
    raw: bytes
    analysis: CaptureAnalysis
    frames: tuple[DspFrame, ...]
    profile: DspProfile | None = None
    state_restored: bool | None = None
    byte_limit_reached: bool = False
    cleanup_errors: tuple[str, ...] = ()

    @classmethod
    def from_bytes(cls, raw: bytes) -> DspCapture:
        """Dissect an existing wire capture and verify frame CRCs before decoding."""
        raw = bytes(raw)
        analysis = analyze_capture(raw)
        frames = []
        cursor = payload_offset = 0
        for message in analysis.messages:
            if not isinstance(message, BinaryMessage):
                continue
            offset = raw.find(message.raw, cursor)
            cursor = offset + len(message.raw)
            record = None
            error = None
            try:
                record = decode_dsp(message)
            except ProtocolError as failure:
                error = str(failure)
            frames.append(
                DspFrame(
                    offset,
                    payload_offset,
                    message,
                    record,
                    error,
                    scan_packets(message.payload),
                )
            )
            payload_offset += len(message.payload)
        return cls(raw, analysis, tuple(frames))

    @property
    def baseband_packets(self) -> tuple[RawBasebandPacket, ...]:
        return tuple(packet for frame in self.frames for packet in frame.baseband)

    @property
    def payloads(self) -> bytes:
        return b"".join(frame.message.payload for frame in self.frames)

    def manifest(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "bytes": len(self.raw),
            "sha256": sha256(self.raw).hexdigest(),
            "binary_ids": dict(self.analysis.binary_ids),
            "binary_payload_bytes": self.analysis.binary_payload_bytes,
            "payload_sha256": sha256(self.payloads).hexdigest(),
            "baseband_packets": len(self.baseband_packets),
            "frames": [frame.manifest() for frame in self.frames],
            "replies": [
                {"command": m.command, "status": m.status}
                for m in self.analysis.replies
            ],
            "decoder_errors": self.analysis.decoder_errors,
            "discarded_bytes": self.analysis.discarded_bytes,
            "pending_bytes": self.analysis.pending_bytes,
            "state_restored": self.state_restored,
            "byte_limit_reached": self.byte_limit_reached,
            "cleanup_errors": self.cleanup_errors,
        }

    def save(self, directory: str | Path) -> Path:
        """Write the capture bytes, payloads and decoded fields to a directory."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "capture.bin").write_bytes(self.raw)
        (directory / "payloads.bin").write_bytes(self.payloads)
        report = json.dumps(self.manifest(), indent=2) + "\n"
        (directory / "report.json").write_text(report)
        return directory


class DspCaptureError(UM982Error):
    """Reports a failed capture with partial bytes and cleanup status."""

    def __init__(self, message: str, capture: DspCapture) -> None:
        super().__init__(message)
        self.capture = capture


def capture_dsp(
    receiver: Receiver,
    profile: DspProfile | str = DspProfile.OBSERVATIONS,
    *,
    seconds: float = 3,
    max_bytes: int = 8 * 1024 * 1024,
) -> DspCapture:
    """Capture DSP observations, then restore receiver state."""
    profile = DspProfile(profile)
    if isinstance(seconds, bool) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be finite and positive")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    with receiver._lock:
        before = receiver_state(receiver)
        existing = receiver.execute(log_list())
        subscriptions = profile.subscriptions()
        targets = {name for name, _, _ in subscriptions}
        if any(entry.name in targets for entry in existing.entries):
            raise ValueError("Capture target already subscribed")
        original = receiver.transport
        tap = RecordingTransport(original, max_bytes)
        stops = []
        cleanup_errors = []
        failure: Exception | None = None
        restored = False
        receiver.transport = tap
        try:
            for _, start, stop in subscriptions:
                stops.append(stop)
                receiver.execute(start)
            receiver._incoming.clear()
            deadline = monotonic() + seconds
            while len(tap.raw) < max_bytes and monotonic() < deadline:
                size = min(65536, max_bytes - len(tap.raw))
                remaining = min(0.1, max(0, deadline - monotonic()))
                receiver.decoder.feed(tap.read(size, remaining))
        except Exception as error:
            failure = error
        finally:
            tap.recording = False
            try:
                for stop in reversed(stops):
                    try:
                        receiver.execute(stop)
                    except Exception as error:
                        cleanup_errors.append(str(error))
            finally:
                receiver.transport = original
            try:
                restored = receiver_state(receiver) == before
            except Exception as error:
                cleanup_errors.append(str(error))
        capture = replace(
            DspCapture.from_bytes(bytes(tap.raw)),
            profile=profile,
            state_restored=restored,
            byte_limit_reached=len(tap.raw) >= max_bytes,
            cleanup_errors=tuple(cleanup_errors),
        )
        if failure is not None or cleanup_errors or not restored:
            message = str(failure or "DSP capture state restoration failed")
            raise DspCaptureError(message, capture) from failure
        return capture
