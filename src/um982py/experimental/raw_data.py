"""Raw-data dump paths and temporary capture."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING, Self

from um982py.commands import logging
from um982py.commands.core import Command, action
from um982py.commands.types import Port, Trigger
from um982py.experimental.baseband import BasebandStream, RawBasebandPacket
from um982py.experimental.baseband_command import bb_message_to_ap
from um982py.experimental.baseband_reply import BasebandNotice, scan_notices
from um982py.experimental.capture import (
    RecordingTransport,
    analyze_capture,
    receiver_state,
)
from um982py.experimental.debug import InternalDebugLog
from um982py.messages import CommandResponse, Sentence
from um982py.receiver_queries import log_list

if TYPE_CHECKING:
    from um982py.receiver import Receiver


class BasebandStage(StrEnum):
    """A baseband stage from the antenna to the position fix."""

    RF_FRONTEND = "rf_frontend"
    ADC = "adc"
    CORRELATOR = "correlator"
    TRACKING = "tracking"
    MEASUREMENT = "measurement"
    NAVIGATION = "navigation"


STAGE_ACCESS: dict[BasebandStage, tuple[str, ...]] = {
    BasebandStage.RF_FRONTEND: (
        "RFSPIREAD/RFSPIWRITE (RF SPI registers)",
        "$RF Chan AGC (baseband diagnostic)",
    ),
    BasebandStage.ADC: (
        "$GROUP ... IFreq, Fs (sample clock and rate)",
        "$SmpClkInit (sample-clock configuration)",
        "CONFIG SIGNALGROUP (band selection that fixes the sample rate)",
    ),
    BasebandStage.CORRELATOR: (
        "Acquisition and correlation diagnostics",
        "$MonitorCorAcqChan (baseband diagnostic)",
        "$PT (per-channel correlator dump on baseband debug UART)",
    ),
    BasebandStage.TRACKING: (
        "Tracking-loop diagnostics",
        "PTOBSINFO (inner message 24, 18 diagnostic slots)",
        "RAWBBPKG containers (when emitted)",
    ),
    BasebandStage.MEASUREMENT: (
        "RANGE / RANGEH logs (pseudorange, carrier phase, Doppler, C/N0)",
    ),
    BasebandStage.NAVIGATION: (
        "BESTPOS / BESTXYZ / SATVIS logs",
        "FASTDEBUGMSG / MPTDEBUGMSG / PPPDEBUGMSG (internal filter telemetry)",
    ),
}


def closest_access(stage: BasebandStage | str) -> tuple[str, ...]:
    """Return the access paths nearest to ``stage``."""
    return STAGE_ACCESS[BasebandStage(stage)]


class RawDataLog(StrEnum):
    """Builds raw baseband dump and subscription commands."""

    SAMPLE_DATA = "DATASAMPLE"
    BASEBAND_TRANSFER = "TRANSBBPKG"
    RAW_DATA = "RAWDATAB"
    RAW_DATA_ASCII = "RAWDATAA"
    RAW_DATA_SECONDARY = "RAWDATAHB"
    RAW_DATA_SECONDARY_ASCII = "RAWDATAHA"
    BASEBAND_PACKAGES = "RAWBBPKG"

    def once(self) -> Command[CommandResponse]:
        """Request the path and match only its command acknowledgement."""
        return action(self.value)

    def output(
        self, interval: float | Trigger = 1, *, port: Port | None = None
    ) -> Command[CommandResponse]:
        return logging.output(self.value, interval, port=port)

    def stop(self, *, port: Port | None = None) -> Command[CommandResponse]:
        return logging.stop(self.value, port=port)

    @property
    def carries_baseband_containers(self) -> bool:
        """Return true only for the path with a container output."""
        return self == self.BASEBAND_PACKAGES


@dataclass(frozen=True, slots=True)
class BasebandCapture:
    """Captured wire bytes and what they parse to."""

    raw: bytes
    packets: tuple[RawBasebandPacket, ...]
    notices: tuple[BasebandNotice, ...]
    discarded_bytes: int
    byte_limit_reached: bool
    state_restored: bool
    cleanup_errors: tuple[str, ...]
    command: str | None = None
    acknowledged: bool | None = None
    subscription_registered: bool | None = None
    pending_bytes: int = 0
    gate_command_sent: bool = False

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        byte_limit_reached: bool = False,
        state_restored: bool = True,
        cleanup_errors: tuple[str, ...] = (),
        max_length: int = 0x4000,
        command: str | None = None,
        acknowledged: bool | None = None,
        subscription_registered: bool | None = None,
        gate_command_sent: bool = False,
    ) -> Self:
        stream = BasebandStream(max_length=max_length)
        packets = stream.feed(raw)
        return cls(
            bytes(raw),
            packets,
            scan_notices(raw),
            stream.discarded,
            byte_limit_reached,
            state_restored,
            cleanup_errors,
            command,
            acknowledged,
            subscription_registered,
            len(stream.pending),
            gate_command_sent,
        )

    def manifest(self) -> dict[str, object]:
        wire = analyze_capture(self.raw)
        return {
            "bytes": len(self.raw),
            "baseband_packets": len(self.packets),
            "notices": len(self.notices),
            "discarded_bytes": self.discarded_bytes,
            "pending_bytes": self.pending_bytes,
            "command": self.command,
            "acknowledged": self.acknowledged,
            "subscription_registered": self.subscription_registered,
            "gate_command_sent": self.gate_command_sent,
            "normal_frames": len(wire.messages),
            "nmea_sentences": sum(isinstance(m, Sentence) for m in wire.messages),
            "binary_ids": dict(wire.binary_ids),
            "normal_decoder_errors": list(wire.decoder_errors),
            "byte_limit_reached": self.byte_limit_reached,
            "state_restored": self.state_restored,
            "cleanup_errors": list(self.cleanup_errors),
            "packets": [packet.manifest() for packet in self.packets],
            "notice_details": [
                {"name": notice.name, "fields": list(notice.fields)}
                for notice in self.notices
            ],
        }


def capture_baseband(
    receiver: Receiver,
    log: RawDataLog | str = RawDataLog.BASEBAND_PACKAGES,
    *,
    seconds: float = 3,
    max_bytes: int = 8 * 1024 * 1024,
    max_length: int = 0x4000,
    enable_gate: bool = False,
    interval: float | Trigger = 1,
    port: Port | None = None,
) -> BasebandCapture:
    """Capture a temporary RAW request and separate ACK, registration and data."""
    return _capture(
        receiver,
        RawDataLog(log).value,
        seconds=seconds,
        max_bytes=max_bytes,
        max_length=max_length,
        enable_gate=enable_gate,
        interval=interval,
        port=port,
    )


def capture_baseband_notices(
    receiver: Receiver,
    *,
    seconds: float = 3,
    max_bytes: int = 8 * 1024 * 1024,
    enable_gate: bool = False,
    port: Port = Port.COM1,
) -> BasebandCapture:
    """Capture BBNOTICE ONCHANGED diagnostic text instead of ADC/IQ samples."""
    return _capture(
        receiver,
        "BBNOTICE",
        seconds=seconds,
        max_bytes=max_bytes,
        max_length=0x4000,
        enable_gate=enable_gate,
        interval=Trigger.ON_CHANGED,
        port=Port(port),
    )


def capture_internal_debug(
    receiver: Receiver,
    log: InternalDebugLog | str = InternalDebugLog.PPP_DEBUG,
    *,
    seconds: float = 3,
    max_bytes: int = 8 * 1024 * 1024,
    interval: float | Trigger | None = None,
    port: Port = Port.COM1,
) -> BasebandCapture:
    """Capture a registered internal filter debug stream and restore receiver state."""
    selected = InternalDebugLog(log)
    chosen_interval: float | Trigger = (
        (Trigger.ON_CHANGED if selected.onchanged_only else 1.0)
        if interval is None
        else interval
    )
    if selected.onchanged_only and chosen_interval != Trigger.ON_CHANGED:
        raise ValueError(f"{selected.value} requires ONCHANGED output")
    prerequisite = (
        "PPPNAVB"
        if selected
        in (
            InternalDebugLog.PPP_DEBUG,
            InternalDebugLog.PPP_DEBUG_SECONDARY,
            InternalDebugLog.MPPP_DEBUG,
            InternalDebugLog.MPPP_DEBUG_SECONDARY,
        )
        else None
    )
    return _capture(
        receiver,
        selected.value,
        seconds=seconds,
        max_bytes=max_bytes,
        max_length=0x4000,
        enable_gate=False,
        interval=chosen_interval,
        port=Port(port),
        prerequisite=prerequisite,
    )


def _capture(
    receiver: Receiver,
    log_name: str,
    *,
    seconds: float,
    max_bytes: int,
    max_length: int,
    enable_gate: bool,
    interval: float | Trigger,
    port: Port | None,
    prerequisite: str | None = None,
) -> BasebandCapture:
    subscription = logging.output(log_name, interval, port=port)
    stop = logging.stop(log_name, port=port)
    if isinstance(seconds, bool) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be finite and positive")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if type(max_length) is not int or max_length < 0x35:
        raise ValueError("max_length must be an integer >= 0x35")
    with receiver._lock:
        before = receiver_state(receiver)
        existing = receiver.execute(log_list())
        if any(entry.name == log_name for entry in existing.entries):
            raise ValueError(f"{log_name} is already subscribed")
        need_prerequisite = prerequisite is not None and not any(
            entry.name == prerequisite for entry in existing.entries
        )
        original = receiver.transport
        tap = RecordingTransport(original, max_bytes)
        gate_sent = False
        prerequisite_sent = False
        registered = False
        cleanup_errors: list[str] = []
        restored = False
        receiver.transport = tap
        try:
            if enable_gate:
                receiver.execute(bb_message_to_ap(enabled=True))
                gate_sent = True
            if need_prerequisite and prerequisite is not None:
                receiver.execute(logging.output(prerequisite, 1, port=port))
                prerequisite_sent = True
            receiver.execute(subscription)
            registered = any(
                entry.name == log_name and (port is None or entry.port == Port(port))
                for entry in receiver.execute(log_list()).entries
            )
            receiver._incoming.clear()
            deadline = monotonic() + seconds
            while len(tap.raw) < max_bytes and monotonic() < deadline:
                size = min(65536, max_bytes - len(tap.raw))
                remaining = min(0.1, max(0, deadline - monotonic()))
                receiver.decoder.feed(tap.read(size, remaining))
        finally:
            tap.recording = False
            try:
                cleanup = [stop]
                if prerequisite_sent and prerequisite is not None:
                    cleanup.append(logging.stop(prerequisite, port=port))
                if gate_sent:
                    cleanup.append(bb_message_to_ap(enabled=False))
                for command in cleanup:
                    try:
                        receiver.execute(command)
                    except Exception as error:  # pragma: no cover
                        cleanup_errors.append(f"{command.text}: {error}")
            finally:
                receiver.transport = original
            try:
                restored = receiver_state(receiver) == before and not cleanup_errors
            except Exception as error:  # pragma: no cover
                cleanup_errors.append(str(error))
    return BasebandCapture.from_bytes(
        bytes(tap.raw),
        byte_limit_reached=len(tap.raw) >= max_bytes,
        state_restored=restored,
        cleanup_errors=tuple(cleanup_errors),
        max_length=max_length,
        command=subscription.text,
        acknowledged=True,
        subscription_registered=registered,
        gate_command_sent=gate_sent,
    )


__all__ = [
    "STAGE_ACCESS",
    "BasebandCapture",
    "BasebandStage",
    "RawDataLog",
    "capture_baseband",
    "capture_baseband_notices",
    "capture_internal_debug",
    "closest_access",
]
