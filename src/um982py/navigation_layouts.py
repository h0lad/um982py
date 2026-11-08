"""Navigation layouts and visibility framing."""

import re
from dataclasses import replace

from um982py.errors import ProtocolError
from um982py.messages.layouts import LAYOUTS as DOCUMENTED
from um982py.messages.reader import BodyReader
from um982py.messages.schema import Field, Group, Layout

BESTXYZ = replace(DOCUMENTED["BESTNAVXYZ"], name="BESTXYZ", table="extended")
PSRDOP = Layout(
    "PSRDOP",
    "extended",
    (
        *DOCUMENTED["DOPHD2"].fields[:-1],
        replace(DOCUMENTED["DOPHD2"].fields[-1], limit=80),
    ),
    None,
)
REFSTATION = Layout(
    "REFSTATION",
    "extended",
    (
        Field("flags", "x", 0, 4),
        Field("coordinate_1", "d", 4, 8),
        Field("coordinate_2", "d", 12, 8),
        Field("coordinate_3", "d", 20, 8),
        Field("field_5", "u", 28, 4),
        Field("field_6", "e", 32, 4),
        Field("field_7", "s", 36, 8),
    ),
    44,
)
_VISIBILITY_FIELDS = (
    Field("status", "u", 4, 4),
    Field("elevation", "d", 8, 8),
    Field("azimuth", "d", 16, 8),
    Field("field_6", "d", 24, 8),
    Field("field_7", "d", 32, 8),
)
SATVIS = Layout(
    "SATVIS",
    "extended",
    (
        Field("flag_1", "e", 0, 4),
        Field("flag_2", "e", 4, 4),
        Field("count", "u", 8, 4),
        Group(
            "satellites",
            12,
            (
                Field("prn", "u", 0, 2),
                Field("channel", "u", 2, 2),
                *_VISIBILITY_FIELDS,
            ),
            "count",
            40,
            limit=240,
        ),
    ),
    None,
)
SATVIS2 = Layout(
    "SATVIS2",
    "extended",
    (
        Field("constellation", "e", 0, 4),
        Field("flag_1", "e", 4, 4),
        Field("flag_2", "e", 8, 4),
        Field("count", "u", 12, 4),
        Group(
            "satellites",
            16,
            (
                Field("channel", "i", 0, 2),
                Field("prn", "u", 2, 2),
                *_VISIBILITY_FIELDS,
            ),
            "count",
            40,
            limit=240,
        ),
    ),
    None,
)
LAYOUTS = {
    layout.name: layout for layout in (BESTXYZ, PSRDOP, REFSTATION, SATVIS, SATVIS2)
}
LAYOUTS.update(
    {name: replace(PSRDOP, name=name) for name in ("PSRDOP2", "RTKDOP", "RTKDOP2")}
)


def visibility_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Expand SATVIS2's PRN[+/-channel] ASCII token into its binary field order."""
    try:
        count = int(fields[3])
        BodyReader.bound(count, 240)
        if len(fields) != 4 + count * 6:
            raise ProtocolError("SATVIS2 count does not match its fields")
        tokens = list(fields[:4])
        for index in range(count):
            start = 4 + index * 6
            satellite = re.fullmatch(r"(\d+)([+-]\d+)?", fields[start])
            if satellite is None:
                raise ProtocolError("Invalid SATVIS2 satellite ID")
            tokens.extend((satellite[2] or "0", satellite[1]))
            tokens.extend(fields[start + 1 : start + 6])
        return tuple(tokens)
    except (IndexError, ValueError) as error:
        raise ProtocolError("Invalid SATVIS2 count") from error
