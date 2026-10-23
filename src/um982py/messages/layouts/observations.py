"""Observation and range body layouts."""

from um982py.messages.schema import Field, Group, Layout

LAYOUTS = (
    Layout(
        "OBSVM",
        "7-52",
        (
            Field(name="obs_number", kind="u", offset=0, size=4),
            Group(
                name="observations",
                offset=4,
                fields=(
                    Field(name="system_freq", kind="u", offset=0, size=2),
                    Field(name="prn_slot", kind="u", offset=2, size=2),
                    Field(name="psr", kind="d", offset=4, size=8),
                    Field(name="adr", kind="d", offset=12, size=8),
                    Field(name="psr_std", kind="u", offset=20, size=2),
                    Field(name="adr_std", kind="u", offset=22, size=2),
                    Field(name="dopp", kind="f", offset=24, size=4),
                    Field(name="c_n0", kind="u", offset=28, size=2),
                    Field(name="reserved", kind="u", offset=30, size=2),
                    Field(name="locktime", kind="f", offset=32, size=4),
                    Field(name="ch_tr_status", kind="x", offset=36, size=4),
                ),
                count="obs_number",
                stride=40,
            ),
        ),
        None,
    ),
    Layout(
        "OBSVH",
        "7-56",
        (
            Field(name="obs_number", kind="u", offset=0, size=4),
            Group(
                name="observations",
                offset=4,
                fields=(
                    Field(name="system_freq", kind="u", offset=0, size=2),
                    Field(name="prn_slot", kind="u", offset=2, size=2),
                    Field(name="psr", kind="d", offset=4, size=8),
                    Field(name="adr", kind="d", offset=12, size=8),
                    Field(name="psr_std", kind="u", offset=20, size=2),
                    Field(name="adr_std", kind="u", offset=22, size=2),
                    Field(name="dopp", kind="f", offset=24, size=4),
                    Field(name="c_n0", kind="u", offset=28, size=2),
                    Field(name="reserved", kind="u", offset=30, size=2),
                    Field(name="locktime", kind="f", offset=32, size=4),
                    Field(name="ch_tr_status", kind="x", offset=36, size=4),
                ),
                count="obs_number",
                stride=40,
            ),
        ),
        None,
    ),
    Layout(
        "OBSVMCMP",
        "7-59",
        (
            Field(name="obs_number", kind="u", offset=0, size=4),
            Group(
                name="observations",
                offset=4,
                fields=(Field(name="cmp_record", kind="b", offset=0, size=24),),
                count="obs_number",
                stride=24,
            ),
        ),
        None,
    ),
    Layout(
        "OBSVHCMP",
        "7-61",
        (
            Field(name="obs_number", kind="u", offset=0, size=4),
            Group(
                name="observations",
                offset=4,
                fields=(Field(name="cmp_record", kind="b", offset=0, size=24),),
                count="obs_number",
                stride=24,
            ),
        ),
        None,
    ),
    Layout(
        "OBSVBASE",
        "7-62",
        (
            Field(name="obs_number", kind="u", offset=0, size=4),
            Group(
                name="observations",
                offset=4,
                fields=(
                    Field(name="system_freq", kind="u", offset=0, size=2),
                    Field(name="prn_slot", kind="u", offset=2, size=2),
                    Field(name="psr", kind="d", offset=4, size=8),
                    Field(name="adr", kind="d", offset=12, size=8),
                    Field(name="psr_std", kind="u", offset=20, size=2),
                    Field(name="adr_std", kind="u", offset=22, size=2),
                    Field(name="dopp", kind="f", offset=24, size=4),
                    Field(name="c_n0", kind="u", offset=28, size=2),
                    Field(name="reserved", kind="u", offset=30, size=2),
                    Field(name="locktime", kind="f", offset=32, size=4),
                    Field(name="ch_tr_status", kind="x", offset=36, size=4),
                ),
                count="obs_number",
                stride=40,
            ),
        ),
        None,
    ),
)
