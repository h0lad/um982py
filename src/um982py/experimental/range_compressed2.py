"""Native RANGECMP2 blocks for compression experiments."""

from dataclasses import dataclass
from math import ceil, floor, isfinite

from um982py.antenna import antenna_index
from um982py.commands import logging
from um982py.commands.core import Command
from um982py.commands.types import Port, Trigger
from um982py.errors import ProtocolError
from um982py.messages import BinaryMessage, CommandResponse, Message

_LOGS = {1: ("RANGECMP2B", 1273), 2: ("RANGECMP2HB", 2112)}
_IDS = {message_id: antenna for antenna, (_, message_id) in _LOGS.items()}
GPS_L1_CODE_WINDOW_M = 128
GPS_L1_CODE_STEP_M = 1 / 128


@dataclass(frozen=True, slots=True)
class Compressed2Signal:
    """Native signal word and the fields used to audit its range offsets."""

    word: int

    @property
    def signal_type(self) -> int:
        return self.word & 31

    @property
    def code_locked(self) -> bool:
        return bool(self.word & (1 << 7))

    @property
    def phase_locked(self) -> bool:
        return bool(self.word & (1 << 5))

    @property
    def pseudorange_offset_m(self) -> float:
        return ((self.word >> 45) & 0x3FFF) / 128

    @property
    def phase_offset_m(self) -> float:
        return ((self.word >> 59) & 0xFFFFF) / 2048

    @property
    def phase_at_ceiling(self) -> bool:
        return (self.word >> 59) & 0xFFFFF == 0xFFFFF


@dataclass(frozen=True, slots=True)
class Compressed2Satellite:
    """Satellite identifier, shared encoded range base and signal words."""

    prn: int
    system: int
    range_base_m: int
    signals: tuple[Compressed2Signal, ...]

    def resolve_gps_l1_code(
        self, *, reference_m: float, max_reference_error_m: float
    ) -> float | None:
        """Recover the code only if an independent bound admits a single fold.

        The reference must describe the same GPS L1 C/A pseudorange, including
        receiver clock bias, at the same epoch. The bound covers reference
        error. One encoded step is added for receiver quantization.
        """
        if (
            not isfinite(reference_m)
            or reference_m <= 0
            or not isfinite(max_reference_error_m)
            or not 0 <= max_reference_error_m < GPS_L1_CODE_WINDOW_M
        ):
            raise ValueError(
                "expected a positive code reference and an error bound in [0, 128) m"
            )
        if self.system != 0:
            return None
        l1 = [
            signal
            for signal in self.signals
            if signal.signal_type == 1 and signal.code_locked
        ]
        if len(l1) != 1:
            return None
        code = self.range_base_m + l1[0].pseudorange_offset_m
        distance = reference_m - code
        margin = max_reference_error_m + GPS_L1_CODE_STEP_M
        first = ceil((distance - margin) / GPS_L1_CODE_WINDOW_M)
        last = floor((distance + margin) / GPS_L1_CODE_WINDOW_M)
        if first != last:
            return None
        resolved = code + first * GPS_L1_CODE_WINDOW_M
        return resolved if resolved > 0 else None


@dataclass(frozen=True, slots=True)
class CompressedRange2:
    """A binary RANGECMP2 frame with its native satellite blocks."""

    message: BinaryMessage
    antenna: int
    satellites: tuple[Compressed2Satellite, ...]


def decode_rangecmp2(message: Message) -> CompressedRange2:
    """Read native blocks without reconstructing absolute observations."""
    if not isinstance(message, BinaryMessage) or message.header.message_id not in _IDS:
        raise ProtocolError("Expected a binary RANGECMP2 frame")
    body = message.payload
    if len(body) < 4 or int.from_bytes(body[:4], "little") != len(body) - 4:
        raise ProtocolError("Invalid RANGECMP2 body length")
    satellites: list[Compressed2Satellite] = []
    offset = 4
    while offset < len(body):
        if len(body) - offset < 10:
            raise ProtocolError("Truncated RANGECMP2 satellite block")
        header = int.from_bytes(body[offset : offset + 10], "little")
        offset += 10
        end = offset + 12 * (header >> 76)
        if end > len(body):
            raise ProtocolError("Truncated RANGECMP2 signal block")
        signals = tuple(
            Compressed2Signal(int.from_bytes(body[index : index + 12], "little"))
            for index in range(offset, end, 12)
        )
        satellites.append(
            Compressed2Satellite(
                prn=(header >> 8) & 255,
                system=(header >> 20) & 31,
                range_base_m=(header >> 26) & 0x1FFFFFFF,
                signals=signals,
            )
        )
        offset = end
    return CompressedRange2(message, _IDS[message.header.message_id], tuple(satellites))


def rangecmp2_read(
    *, antenna: int | str = 1, port: Port | None = None
) -> Command[CompressedRange2]:
    """Request native binary RANGECMP2 blocks for the selected antenna."""
    name, message_id = _LOGS[antenna_index(antenna)]
    return logging.request(name, port=port, message_id=message_id).decoded_with(
        decode_rangecmp2
    )


def rangecmp2_output(
    interval: float | Trigger = 1, *, antenna: int | str = 1, port: Port | None = None
) -> Command[CommandResponse]:
    """Subscribe to native binary RANGECMP2 blocks."""
    name, _ = _LOGS[antenna_index(antenna)]
    return logging.output(name, interval, port=port)


def rangecmp2_stop(
    *, antenna: int | str = 1, port: Port | None = None
) -> Command[CommandResponse]:
    """Stop a RANGECMP2 subscription for the selected antenna."""
    name, _ = _LOGS[antenna_index(antenna)]
    return logging.stop(name, port=port)
