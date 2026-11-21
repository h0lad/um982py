"""RF signal profiles and automatic gain diagnostics."""

from dataclasses import dataclass
from struct import unpack

from um982py.commands.types import Constellation
from um982py.errors import ProtocolError
from um982py.experimental.baseband import BasebandMessage
from um982py.messages import Record

AGC_MESSAGE_ID = 23
_RF_WORDS_BY_CHANNEL = (6, 8, 7, 5, 4, 1, 3, 2)

_SYSTEMS = (
    Constellation.GPS,
    Constellation.GLONASS,
    Constellation.GALILEO,
    Constellation.BDS,
    Constellation.QZSS,
    Constellation.NAVIC,
)
_BINARY_SYSTEMS = dict(enumerate(_SYSTEMS, 1))
_ASCII_SYSTEMS = dict(zip(("GP", "GL", "GA", "GB", "GQ", "GI"), _SYSTEMS, strict=True))
_BAND_BITS = {
    Constellation.GPS: ((0x01, "L1"), (0x0C, "L2"), (0x10, "L5")),
    Constellation.GLONASS: ((0x01, "G1"), (0x02, "G2"), (0x04, "G3")),
    Constellation.GALILEO: ((0x01, "E1"), (0x02, "E5a"), (0x04, "E5b"), (0x08, "E6")),
    Constellation.BDS: ((0x01, "B1I"), (0x04, "B3I")),
}


@dataclass(frozen=True, slots=True)
class AntennaSignalMask:
    """One constellation row from the antenna's configured profile."""

    system: int | str
    constellation: Constellation | None
    mask: int

    @property
    def bands(self) -> tuple[str, ...]:
        """Recognized band families advertised by the profile."""
        if self.constellation is None:
            return ()
        return tuple(
            name
            for bits, name in _BAND_BITS.get(self.constellation, ())
            if self.mask & bits
        )

    @property
    def unknown_bits(self) -> int:
        """Retain advertised bits with no band assignment."""
        known = 0
        if self.constellation is not None:
            for bits, _ in _BAND_BITS.get(self.constellation, ()):
                known |= bits
        return self.mask & ~known


@dataclass(frozen=True, slots=True)
class AntennaSignalProfile:
    """Signal group ID and advertised signal masks for ANT1 or ANT2."""

    antenna: int
    group: int
    masks: tuple[AntennaSignalMask, ...]

    @classmethod
    def from_record(cls, record: Record) -> "AntennaSignalProfile":
        if record.name not in ("ANT1GROUP", "ANT2GROUP"):
            raise ValueError("expected an ANT1GROUP or ANT2GROUP record")
        masks = []
        for row in record.records("groups"):
            system = row["system"]
            if isinstance(system, int):
                constellation = _BINARY_SYSTEMS.get(system)
            elif isinstance(system, str):
                constellation = _ASCII_SYSTEMS.get(system)
            else:
                raise ValueError("expected a binary system code or ASCII system name")
            masks.append(AntennaSignalMask(system, constellation, row.integer("mask")))
        return cls(
            1 if record.name == "ANT1GROUP" else 2,
            record.integer("field_01"),
            tuple(masks),
        )


def _gain(value: int) -> int | None:
    return None if value == -1 else value


@dataclass(frozen=True, slots=True)
class AgcReadings:
    """Receiver AGC readings in native units. Unavailable paths are None."""

    ant1_l1: int | None
    ant1_l2: int | None
    ant1_l5: int | None
    ant1_additional: int | None
    ant2_l1: int | None
    ant2_l2: int | None
    ant2_l5: int | None

    @classmethod
    def from_record(cls, record: Record) -> "AgcReadings":
        if record.name != "AGC":
            raise ValueError("expected an AGC record")
        return cls(
            *(
                _gain(record.integer(key))
                for key in (
                    "ant1l1",
                    "ant1l2",
                    "ant1l5",
                    "reserved",
                    "ant2l1",
                    "ant2l2",
                    "ant2l5",
                )
            )
        )


@dataclass(frozen=True, slots=True)
class BasebandAgc:
    """The ten native words of a baseband AGC block."""

    native_words: tuple[int, ...]

    @property
    def rf_channels(self) -> tuple[int, ...]:
        """Return all eight native AGC readings in RF index order."""
        return tuple(self.native_words[index] for index in _RF_WORDS_BY_CHANNEL)

    def readings(self, *, secondary_enabled: bool) -> AgcReadings:
        """Select the AGC words rendered for the given antenna configuration."""
        reported = tuple(
            _gain((value & 0x7FFF) - (value & 0x8000)) for value in self.native_words
        )
        return AgcReadings(
            reported[1],
            reported[2],
            reported[3],
            reported[5],
            reported[6] if secondary_enabled else None,
            reported[7] if secondary_enabled else None,
            reported[8] if secondary_enabled else None,
        )


def decode_agc_message(message: BasebandMessage) -> BasebandAgc:
    """Extract the native AGC block from inner message 23."""
    if message.message_id != AGC_MESSAGE_ID:
        raise ProtocolError("Expected baseband AGC message 23")
    payload = message.decode()["field_12"]
    if not isinstance(payload, bytes):
        raise ProtocolError("Expected a binary AGC body")
    return BasebandAgc(unpack("<10i", payload))
