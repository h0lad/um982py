"""Binary layouts for the extended log families."""

from dataclasses import replace

from um982py.messages.layouts import LAYOUTS as DOCUMENTED
from um982py.messages.layouts.firmware_navigation import LAYOUTS as NAVIGATION
from um982py.messages.schema import Field, Group, Layout

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
GLOCLOCK = Layout(
    "GLOCLOCK",
    "extended",
    (
        Field("reserved", "u", 0, 4),
        Field("reserved_2", "d", 4, 8),
        Field("reserved_3", "d", 12, 8),
        Field("satellite_type", "u", 20, 1),
        Field("four_year_interval", "u", 21, 1),
        Field("tau_gps_s", "d", 24, 8),
        Field("day_number", "u", 32, 2),
        Field("tau_c_s", "d", 36, 8),
        Field("beta1", "d", 44, 8),
        Field("beta2", "d", 52, 8),
        Field("kp", "u", 60, 2),
        Field("receiver_word", "u", 62, 2),
    ),
    64,
)
GLOALMANAC = Layout(
    "GLOALMANAC",
    "extended",
    (
        Field("reference_week", "u", 0, 4),
        Field("reference_tow_s", "u", 4, 4),
        Field("satellite_id", "u", 8, 1),
        Field("frequency_channel", "i", 9, 1),
        Field("satellite_type", "u", 10, 1),
        Field("health", "u", 11, 1),
        Field("ascending_node_time_s", "d", 12, 8),
        Field("ascending_node_longitude_rad", "d", 20, 8),
        Field("inclination_correction_rad", "d", 28, 8),
        Field("eccentricity", "d", 36, 8),
        Field("argument_of_perigee_rad", "d", 44, 8),
        Field("period_correction_s", "d", 52, 8),
        Field("period_rate", "d", 60, 8),
        Field("clock_offset_s", "d", 68, 8),
    ),
    76,
)
GLOALMANAC_ASCII = replace(
    GLOALMANAC,
    fields=(
        GLOALMANAC.fields[0],
        Field("reference_tow_s", "d", 4, 8),
        *GLOALMANAC.fields[2:],
    ),
)
IONUTC = Layout(
    "IONUTC",
    "extended",
    (
        *DOCUMENTED["GPSION"].fields[:8],
        Field("utc_wn", "u", 64, 4),
        Field("tot", "u", 68, 4),
        Field("utc_a0", "d", 72, 8),
        Field("utc_a1", "d", 80, 8),
        Field("wn_lsf", "u", 88, 4),
        Field("dn", "u", 92, 4),
        Field("deltat_ls", "i", 96, 4),
        Field("deltat_lsf", "i", 100, 4),
        Field("reserved", "u", 104, 4),
    ),
    108,
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
        GLOCLOCK,
        GLOALMANAC,
        IONUTC,
        replace(IONUTC, name="BD2IONUTC"),
        RANGE,
        HEADINGOFFSET,
        RXSTATUS,
    )
}
LAYOUTS.update(
    {
        name: replace(POSITION, name=name)
        for name in ("PSRPOS", "MPSRPOS", "MPSRPOS2", "RTKPOS")
    }
)
LAYOUTS["RANGEH"] = replace(RANGE, name="RANGEH")
LAYOUTS["ALGRANGE"] = replace(RANGE, name="ALGRANGE")
LAYOUTS.update(
    {
        name: replace(DOCUMENTED[original], name=name, table="extended")
        for name, original in (
            ("HWSTATUSD", "HWSTATUS"),
            ("RTCSTATUSD", "RTCSTATUS"),
            ("JAMSTATUSD", "JAMSTATUS"),
            ("PVTSOL", "PVTSLN"),
            ("SATXYZ2", "SATECEF"),
            ("EVENTMARK", "EVENTFLAG"),
            ("EVENTALL", "EVENTSLN"),
        )
    }
)
LAYOUTS["BASESATS"] = Layout(
    "BASESATS",
    "extended",
    (
        Field("count", "u", 0, 4),
        Group(
            "observations",
            4,
            (
                Field("prn", "u", 0, 2),
                Field("field_2", "u", 2, 2),
                Field("field_4", "f", 4, 4),
                Field("status_word", "x", 8, 4),
            ),
            "count",
            12,
            limit=240,
        ),
    ),
    None,
)
LAYOUTS["SBAS1"] = Layout(
    "SBAS1",
    "extended",
    (
        Field("source_prn", "u", 0, 4),
        Field("prn_mask", "b", 4, 27),
        Field("field_32", "u", 32, 4),
    ),
    36,
)
LAYOUTS["SBAS18"] = Layout(
    "SBAS18",
    "extended",
    (
        Field("source_prn", "u", 0, 4),
        Field("field_4", "u", 4, 4),
        Field("field_8", "u", 8, 4),
        Field("field_12", "u", 12, 4),
        Field("grid_mask", "b", 16, 26),
        Field("field_44", "u", 44, 4),
    ),
    48,
)
LAYOUTS["REMOTEANTENNAPCO"] = Layout(
    "REMOTEANTENNAPCO",
    "extended",
    (
        Field("north_mm", "d", 0, 8),
        Field("east_mm", "d", 8, 8),
        Field("up_mm", "d", 16, 8),
    ),
    24,
)
LAYOUTS["HEADINGSTATUSD"] = replace(
    DOCUMENTED["HEADINGSTATUS"], name="HEADINGSTATUSD", table="extended"
)

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
LAYOUTS.update({layout.name: layout for layout in (ANTENNA, DOPPVEL)})
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
                Field("system", "e", 0, 4),
                Field("satellite", "sat_channel_first", 4, 4),
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


def _baseline_layout(name: str) -> Layout:
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
            name: _baseline_layout(name)
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
