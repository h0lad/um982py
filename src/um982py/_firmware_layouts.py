"""Binary layouts for the extended log families."""

from dataclasses import replace

from um982py._firmware_navigation import LAYOUTS as NAVIGATION
from um982py.messages.layouts import LAYOUTS as DOCUMENTED
from um982py.messages.schema import Field, Group, Kind, Layout

POSITION = Layout("BESTPOS", "extended", DOCUMENTED["BESTNAV"].fields[:21], 72)
VELOCITY = Layout(
    "BESTVEL",
    "extended",
    (
        *(
            replace(f, offset=f.offset - 72)
            for f in DOCUMENTED["BESTNAV"].fields[21:28]
        ),
        Field("reserved", "u", 40, 4),
    ),
    44,
)
TIME = Layout(
    "TIME",
    "extended",
    (
        Field("clock_status", "e", 0, 4),
        Field("clock_offset", "d", 4, 8),
        Field("clock_offset_std", "d", 12, 8),
        Field("utc_offset", "d", 20, 8),
        Field("year", "u", 28, 4),
        Field("month", "u", 32, 1),
        Field("day", "u", 33, 1),
        Field("hour", "u", 34, 1),
        Field("minute", "u", 35, 1),
        Field("millisecond", "u", 36, 4),
        Field("utc_status", "e", 40, 4),
    ),
    44,
)
RANGE = Layout(
    "RANGE",
    "extended",
    (
        Field("count", "u", 0, 4),
        Group(
            "observations",
            4,
            (
                Field("prn", "u", 0, 2),
                Field("frequency_channel", "u", 2, 2),
                Field("pseudorange", "d", 4, 8),
                Field("pseudorange_std", "f", 12, 4),
                Field("carrier_phase", "d", 16, 8),
                Field("carrier_phase_std", "f", 24, 4),
                Field("doppler", "f", 28, 4),
                Field("cn0", "f", 32, 4),
                Field("lock_time", "f", 36, 4),
                Field("tracking_status", "x", 40, 4),
            ),
            "count",
            44,
            limit=240,
        ),
    ),
    None,
)
HEADINGOFFSET = Layout(
    "HEADINGOFFSET",
    "extended",
    (Field("heading", "f", 0, 4), Field("pitch", "f", 4, 4)),
    8,
)
PPSSTATUS = Layout(
    "PPSSTATUS",
    "extended",
    tuple(
        Field(
            f"field_{i + 1:02}",
            "i" if i in (3, 4, 7) else "x" if i in (5, 6) or i >= 8 else "u",
            i * 4,
            4,
        )
        for i in range(15)
    ),
    60,
)
_ENV_FIELDS: tuple[tuple[Kind, int, int], ...] = (
    ("u", 0, 2),
    ("d", 2, 8),
    ("u", 10, 2),
    ("u", 12, 2),
    ("u", 14, 1),
    ("u", 15, 1),
    ("d", 16, 8),
    ("e", 24, 4),
    ("u", 28, 4),
    ("u", 32, 4),
    ("d", 36, 8),
    ("u", 44, 2),
    ("u", 46, 2),
    ("u", 48, 2),
    ("u", 50, 2),
    ("u", 52, 4),
    ("u", 56, 4),
    ("u", 60, 4),
    ("u", 64, 8),
    ("d", 72, 8),
    ("d", 80, 8),
    ("d", 88, 8),
    ("u", 96, 1),
    ("u", 97, 1),
    ("d", 98, 8),
    ("d", 106, 8),
)
ENVINFO = Layout(
    "ENVINFO",
    "extended",
    tuple(
        Field(f"field_{i + 1:02}", kind, offset, size)
        for i, (kind, offset, size) in enumerate(_ENV_FIELDS)
    ),
    114,
)
RXSTATUS = Layout(
    "RXSTATUS",
    "extended",
    tuple(
        Field(name, "s", 0, 128)
        for name in (
            "model",
            "hardware",
            "clocks",
            "software",
            "rtk_version",
            "baseband_version",
            "loader_version",
            "serial_number",
            "efuse_id",
            "authorization",
            "compiled",
            "field_12",
            "field_13",
            "clock_source",
            "interrupts",
            "dynamics",
        )
    ),
    None,
)

LAYOUTS = {
    layout.name: layout
    for layout in (
        POSITION,
        VELOCITY,
        TIME,
        RANGE,
        HEADINGOFFSET,
        PPSSTATUS,
        ENVINFO,
        RXSTATUS,
    )
}
LAYOUTS.update({name: replace(POSITION, name=name) for name in ("PSRPOS", "RTKPOS")})
LAYOUTS["RANGEH"] = replace(RANGE, name="RANGEH")

ANTENNA = Layout(
    "ANTENNA",
    "extended",
    (
        Field("status_1", "e", 0, 4),
        Field("status_2", "e", 4, 4),
        Field("status_3", "e", 8, 4),
        Field("reserved", "u", 12, 4),
    ),
    16,
)
DOPPVEL = Layout(
    "DOPPVEL",
    "extended",
    tuple(replace(f, offset=f.offset - 72) for f in DOCUMENTED["BESTNAV"].fields[21:]),
    48,
)
SPOOFINFO = Layout(
    "SPOOFINFO",
    "extended",
    (
        Field("position_type", "e", 0, 4),
        Field("spoof_indicator", "u", 4, 4),
        *(
            Field(f"field_{i + 1:02}", "x" if i < 5 else "i", i * 4, 4)
            for i in range(2, 20)
        ),
        *(Field(f"field_{i + 21:02}", "x", 80 + i * 8, 8) for i in range(4)),
        *(Field(f"field_{i + 25:02}", "d", 112 + i * 8, 8) for i in range(3)),
    ),
    136,
)
LAYOUTS.update({layout.name: layout for layout in (ANTENNA, DOPPVEL, SPOOFINFO)})
LAYOUTS["ANTENNASTATUS"] = replace(ANTENNA, name="ANTENNASTATUS")
LAYOUTS["DOPPVELH"] = replace(DOPPVEL, name="DOPPVELH")
LAYOUTS.update(NAVIGATION)
LAYOUTS.update({name: replace(VELOCITY, name=name) for name in ("PSRVEL", "PSRVEL2")})
LAYOUTS["PTOBSINFO"] = Layout(
    "PTOBSINFO",
    "extended",
    tuple(
        Field(
            f"field_{index + 1:02}",
            "f" if index == 5 or index >= 11 else "x" if index == 10 else "u",
            index * 4,
            4,
        )
        for index in range(29)
    ),
    116,
)
BESTSATS = Layout(
    "BESTSATS",
    "extended",
    (
        Field("count", "u", 0, 4),
        Group(
            "satellites",
            4,
            (
                Field("system", "e", 0, 2),
                Field("satellite", "sat", 2, 4),
                Field("state", "e", 8, 4),
                Field("flags", "x", 12, 4),
            ),
            "count",
            16,
            limit=240,
        ),
    ),
    None,
)
ALIGNDOP = replace(DOCUMENTED["DOPHD2"], name="ALIGNDOP", table="extended")


def _baseline(name: str) -> Layout:
    """Describes a baseline vector with three deltas, three sigmas and status."""
    return Layout(
        name,
        "extended",
        (
            Field("p_sol_status", "e", 0, 4),
            Field("pos_type", "e", 4, 4),
            Field("delta_1", "d", 8, 8),
            Field("delta_2", "d", 16, 8),
            Field("delta_3", "d", 24, 8),
            Field("std_1", "f", 32, 4),
            Field("std_2", "f", 36, 4),
            Field("std_3", "f", 40, 4),
            Field("stn_id", "s", 44, 4),
            Field("field_10", "s", 48, 4),
            *(
                Field(f"field_{index:02}", "u", index + 41, 1)
                for index in range(11, 19)
            ),
        ),
        60,
    )


ANTENNA_GROUP = Layout(
    "ANT1GROUP",
    "extended",
    (
        Field("field_01", "u", 0, 2),
        Field("count", "u", 2, 2),
        Group(
            "groups",
            4,
            (Field("system", "e", 0, 2), Field("mask", "x", 2, 2)),
            "count",
            4,
            limit=32,
        ),
    ),
    None,
)
LAYOUTS.update(
    {
        "BESTGNSSPOS": replace(POSITION, name="BESTGNSSPOS"),
        "BESTPOS2": replace(POSITION, name="BESTPOS2"),
        "BESTGNSSVEL": replace(VELOCITY, name="BESTGNSSVEL"),
        "BESTVEL2": replace(VELOCITY, name="BESTVEL2"),
        "BESTSATS": BESTSATS,
        "ALIGNDOP": ALIGNDOP,
        "ANT1GROUP": ANTENNA_GROUP,
        "ANT2GROUP": replace(ANTENNA_GROUP, name="ANT2GROUP"),
        **{
            name: _baseline(name)
            for name in ("BSLNENUHD", "BSLNXYZHD", "ALIGNBSLNENU", "ALIGNBSLNXYZ")
        },
    }
)

LAYOUTS.update(
    {
        name: replace(
            DOCUMENTED["RTKSTATUS"],
            name=name,
        )
        for name in ("RTKSTATUS2", "RTKSTATUSD", "RTKSTATUS2D")
    }
)
LAYOUTS.update(
    {
        name: replace(
            VELOCITY,
            name=name,
            fields=(
                *VELOCITY.fields[:-1],
                Field("reserved", "f", 40, 4),
            ),
        )
        for name in ("RTKVEL", "RTKVEL2")
    }
)
