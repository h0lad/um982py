"""Satellite information decoding."""

from um982py.errors import ProtocolError
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record, Value
from um982py.messages.schema import Field


def satellite_information(data: bytes | tuple[str, ...]) -> Record:
    reader = BodyReader(data)

    def read(name: str, size: int = 1, *, signed: bool = False) -> Value:
        return reader.scalar(
            Field(name, "i" if signed else "u", 0, size), reader.position
        )

    header = tuple(
        (name, read(name))
        for name in (
            "satellite_count",
            "version",
            "reserved",
            "reserved_2",
            "reserved_3",
            "frequency_flags",
        )
    )
    count = Record("SATSINFO", header).integer("satellite_count")
    reader.bound(count)
    satellites = []
    for _ in range(count):
        prefix = (
            ("prn", read("prn")),
            ("azimuth", read("azimuth", 2, signed=True)),
            ("elevation", read("elevation")),
        )

        def frequency() -> Record:
            return Record(
                "frequency",
                tuple(
                    (name, read(name))
                    for name in ("system", "snr", "signal", "frequency_count")
                ),
            )

        first = frequency()
        frequencies = first.integer("frequency_count")
        if not 1 <= frequencies <= 16:
            raise ProtocolError("Invalid SATSINFO frequency count")
        records = (first, *tuple(frequency() for _ in range(frequencies - 1)))
        if any(r.integer("frequency_count") != frequencies for r in records):
            raise ProtocolError("Inconsistent SATSINFO frequency counts")
        satellites.append(Record("satellite", (*prefix, ("frequencies", records))))
    if reader.position != len(data):
        raise ProtocolError("Unexpected SATSINFO trailing data")
    return Record("SATSINFO", (*header, ("satellites", tuple(satellites))))
