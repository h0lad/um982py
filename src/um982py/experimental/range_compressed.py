"""RANGECMP compressed observations with reconstructed carrier phase."""

from dataclasses import dataclass
from struct import unpack_from

from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BinaryMessage, CommandResponse, Message
from um982py.signals import tracking_signal

__all__ = [
    "CompressedObservation",
    "CompressedRange",
    "decode_rangecmp",
    "rangecmp_output",
    "rangecmp_read",
    "rangecmp_stop",
]

_MESSAGE_ID = 140
_ENTRY_SIZE = 24
_HEX_ENTRY_SIZE = 48
_MAX_OBSERVATIONS = 256
_LIGHT_SPEED = 299792458.0
_FOLD = 1 << 24
_HALF_FOLD = 1 << 23
_PSRSTD = (
    0.050,
    0.075,
    0.113,
    0.169,
    0.253,
    0.380,
    0.570,
    0.854,
    1.281,
    2.375,
    4.750,
    9.500,
    19.000,
    38.000,
    76.000,
    152.000,
)


@dataclass(frozen=True, slots=True)
class CompressedObservation:
    """One compressed observation with reconstructed carrier phase."""

    tracking_status: int
    prn: int
    doppler_hz: float
    pseudorange_m: float
    carrier_phase_cycles: float | None
    """Reconstructed absolute carrier phase; None when the signal is unknown."""
    pseudorange_std_m: float
    carrier_phase_std_cycles: float
    lock_time_s: float
    cn0_db_hz: int
    cn0_saturated: bool
    """True when the C/N0 index reached either end of its range."""
    glonass_channel: int
    """Raw six-bit frequency index."""
    divergence_cycles: float | None
    """Code-carrier divergence used for fold selection."""


@dataclass(frozen=True, slots=True)
class CompressedRange:
    """One RANGECMP frame and its decoded compressed observations."""

    message: Message
    observations: tuple[CompressedObservation, ...]


def _unsigned(raw: int, offset: int, width: int) -> int:
    """Extract an unsigned bit field starting at the low bit offset."""
    return (raw >> offset) & ((1 << width) - 1)


def _signed(raw: int, offset: int, width: int) -> int:
    """Extract a signed bit field starting at the low bit offset."""
    value = _unsigned(raw, offset, width)
    return value - (1 << width) if value >= (1 << (width - 1)) else value


def _frequency_hz(status: int, glonass_channel: int) -> float | None:
    """Resolve the carrier frequency, leaving unknown signals unresolved."""
    channel = glonass_channel - 7 if (status >> 16) & 7 == 1 else None
    try:
        signal = tracking_signal(status, glonass_channel=channel)
    except ValueError:
        return None
    if signal is None:
        return None
    return signal.frequency_hz


def _reconstruct_phase(
    adr: int, pseudorange: float, frequency_hz: float
) -> tuple[float, float]:
    """Recover absolute carrier phase and its code-carrier divergence in cycles."""
    fold = round(pseudorange * frequency_hz / _LIGHT_SPEED / _FOLD)
    scaled = pseudorange * frequency_hz / _LIGHT_SPEED
    candidates = tuple(
        adr / 256 - (fold + shift) * _FOLD + half
        for shift in (-1, 0, 1)
        for half in (0, _HALF_FOLD)
    )
    phase = min(candidates, key=lambda candidate: abs(candidate + scaled))
    return phase, phase + scaled


def _decode_entry(raw: int) -> CompressedObservation:
    """Decode one packed entry without retaining its wire bytes."""
    status = _unsigned(raw, 0, 32)
    pseudorange = _unsigned(raw, 60, 36) / 128
    glonass_channel = _unsigned(raw, 170, 6)
    frequency = _frequency_hz(status, glonass_channel)
    cn0 = 20 + _unsigned(raw, 165, 5)
    if frequency is None:
        phase = None
        divergence = None
    else:
        phase, divergence = _reconstruct_phase(
            _signed(raw, 96, 32), pseudorange, frequency
        )
    return CompressedObservation(
        tracking_status=status,
        prn=_unsigned(raw, 136, 8),
        doppler_hz=_signed(raw, 32, 28) / 256,
        pseudorange_m=pseudorange,
        carrier_phase_cycles=phase,
        pseudorange_std_m=_PSRSTD[_unsigned(raw, 128, 4)],
        carrier_phase_std_cycles=(_unsigned(raw, 132, 4) + 1) / 512,
        lock_time_s=_unsigned(raw, 144, 21) / 32,
        cn0_db_hz=cn0,
        cn0_saturated=cn0 in (20, 51),
        glonass_channel=glonass_channel,
        divergence_cycles=divergence,
    )


def _decode_binary(payload: bytes) -> tuple[int, ...]:
    """Unpack binary entries after validating the frame length."""
    if len(payload) < 4:
        raise ProtocolError("Truncated RANGECMP header")
    count = unpack_from("<I", payload, 0)[0]
    if count > _MAX_OBSERVATIONS or len(payload) != 4 + count * _ENTRY_SIZE:
        raise ProtocolError("Invalid RANGECMP entry count or body length")
    return tuple(
        int.from_bytes(
            payload[4 + index * _ENTRY_SIZE : 4 + (index + 1) * _ENTRY_SIZE], "little"
        )
        for index in range(count)
    )


def _decode_ascii(fields: tuple[str, ...]) -> tuple[int, ...]:
    """Unpack hexadecimal entries after validating the field count."""
    if not fields:
        raise ProtocolError("Truncated RANGECMP header")
    try:
        count = int(fields[0])
    except ValueError as error:
        raise ProtocolError("Invalid RANGECMP entry count") from error
    entries = fields[1:]
    if (
        count > _MAX_OBSERVATIONS
        or len(entries) != count
        or any(len(entry) != _HEX_ENTRY_SIZE for entry in entries)
    ):
        raise ProtocolError("Invalid RANGECMP entry count or body length")
    try:
        return tuple(
            int.from_bytes(bytes.fromhex(entry), "little") for entry in entries
        )
    except ValueError as error:
        raise ProtocolError("Invalid RANGECMP entry encoding") from error


def decode_rangecmp(message: Message) -> CompressedRange:
    """Decode a binary or ASCII RANGECMP frame into compressed observations."""
    if isinstance(message, BinaryMessage):
        if message.header.message_id != _MESSAGE_ID:
            raise ProtocolError("Expected RANGECMPB message ID 140")
        raws = _decode_binary(message.payload)
    elif isinstance(message, AsciiMessage) and message.name == "RANGECMPA":
        raws = _decode_ascii(message.fields)
    else:
        raise ProtocolError("Expected a RANGECMP frame")
    return CompressedRange(message, tuple(_decode_entry(raw) for raw in raws))


def rangecmp_read(*, port: Port | None = None) -> Command[CompressedRange]:
    """Request one binary RANGECMP frame."""
    request = logging.request("RANGECMPB", port=port, message_id=_MESSAGE_ID)
    return Command(request.text, request.matches, decode_rangecmp)


def rangecmp_output(
    interval: float | Trigger = 1, *, port: Port | None = None
) -> Command[CommandResponse]:
    """Subscribe to binary compressed observations."""
    return logging.output("RANGECMPB", interval, port=port)


def rangecmp_stop(*, port: Port | None = None) -> Command[CommandResponse]:
    """Stop a previously started compressed observation subscription."""
    return logging.stop("RANGECMPB", port=port)
