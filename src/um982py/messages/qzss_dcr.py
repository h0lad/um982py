"""Decode the QZSS L1S disaster report carried in a QZQSM sentence."""
#  Bit positions follow IS-QZSS-DCR-010, section 4.1.2, and IS-QZSS-L1S-008.
# The category-specific decoder currently supports version 1 weather reports.

from dataclasses import dataclass

from um982py.messages.record import Record

_CATEGORIES = {
    1: "earthquake early warning",
    2: "hypocenter",
    3: "seismic intensity",
    4: "Nankai Trough earthquake",
    5: "tsunami",
    6: "northwest Pacific tsunami",
    8: "volcano",
    9: "ash fall",
    10: "weather",
    11: "flood",
    12: "typhoon",
    14: "marine",
}
_CLASSIFICATIONS = {
    1: "maximum priority",
    2: "priority",
    3: "regular",
    7: "training/test",
}
_INFORMATION_TYPES = {0: "issue", 1: "correction", 2: "cancellation"}


@dataclass(frozen=True, slots=True)
class WeatherRegion:
    subcategory_code: int
    region_code: int


@dataclass(frozen=True, slots=True)
class WeatherReport:
    # The signal does not include a year. All times are UTC.
    month: int
    day: int
    hour: int
    minute: int
    information_type_code: int
    warning_state_code: int
    regions: tuple[WeatherRegion, ...]

    @property
    def information_type(self) -> str | None:
        return _INFORMATION_TYPES.get(self.information_type_code)


@dataclass(frozen=True, slots=True)
class DisasterReport:
    satellite_number: int
    message_type: int
    classification_code: int | None
    version: int | None
    payload_hex: str
    category_code: int | None = None
    organization_code: int | None = None
    weather: WeatherReport | None = None

    @property
    def classification(self) -> str | None:
        return (
            _CLASSIFICATIONS.get(self.classification_code)
            if self.classification_code is not None
            else None
        )

    @property
    def category(self) -> str | None:
        return (
            _CATEGORIES.get(self.category_code)
            if self.category_code is not None
            else None
        )


def decode_qzqsm(record: Record) -> DisasterReport:
    """Validate and decode a QZQSM record, rejecting corrupt or non-DCR frames.

    Unknown versions and categories are retained without interpreting their body.
    MT44 is retained without interpreting DCR-specific fields: current DCX
    messages and older MT44 formats have different layouts, and the record
    does not establish which format was transmitted.
    This function validates the satellite CRC, while NMEA checksum validation is the
    responsibility of the stream decoder.
    """
    if record.name != "QZQSM":
        raise ValueError("expected a QZQSM record")
    payload = record["dc_message"]
    if (
        not isinstance(payload, str)
        or len(payload) != 63
        or any(c not in "0123456789abcdefABCDEF" for c in payload)
    ):
        raise ValueError("QZQSM payload must contain 63 hexadecimal digits")
    bits = f"{int(payload, 16):0252b}"
    if bits[250:] != "00":
        raise ValueError("nonzero QZQSM padding")
    if int(bits[:8], 2) not in (0x53, 0x9A, 0xC6):
        raise ValueError("invalid L1S preamble")
    message_type = int(bits[8:14], 2)
    if message_type not in (43, 44):
        raise ValueError("not a disaster report message type")
    crc = 0
    for bit in bits[:226]:
        feedback = (crc >> 23) ^ int(bit)
        crc = (crc << 1) & 0xFFFFFF
        if feedback:
            crc ^= 0x864CFB
    if crc != int(bits[226:250], 2):
        raise ValueError("invalid L1S CRC-24Q")

    def field(start: int, end: int) -> int:
        return int(bits[start:end], 2)

    version = field(214, 220) if message_type == 43 else None
    category = field(17, 21) if message_type == 43 else None
    weather = None
    if message_type == 43 and category == 10 and version == 1:
        regions = tuple(
            WeatherRegion(field(start, start + 5), field(start + 5, start + 24))
            for start in range(56, 200, 24)
            if field(start, start + 24)
        )
        weather = WeatherReport(
            field(21, 25),
            field(25, 30),
            field(30, 35),
            field(35, 41),
            field(41, 43),
            field(53, 56),
            regions,
        )
    return DisasterReport(
        record.integer("prn"),
        message_type,
        field(14, 17) if message_type == 43 else None,
        version,
        payload,
        category,
        None,
        weather,
    )
