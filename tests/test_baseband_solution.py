"""Validates structured baseband PVT notices and their agreement checks."""

import pytest

from um982py.errors import ProtocolError
from um982py.experimental import (
    BasebandSolution,
    parse_baseband_notice,
    solution_jump_m,
    solution_separation_m,
)
from um982py.experimental.baseband_reply import BasebandNotice
from um982py.messages.record import Record

NAVPOS_LINE = (
    b"$NAVPOS,1842461,9,16,1,52.520645,13.409484,74.000000,"
    b"3783162.875,901938.310,5038321.497,  20\r\n"
)

NAVVEL_LINE = b"$NAVVEL,0.000,0.000,0.000,0.000,-0.534,  18,    0.000\r\n"

POS_RESULT_LINE = (
    b"$PosResult: 478839000 8 10.159920 6366406.026422;"
    b"3782563.406865 899474.280343 5039206.046713;"
    b" 0.000000 0.000000 0.000000;"
    b"3783162.875 901938.310 5038321.497\r\n"
)


def decode(line: bytes) -> Record:
    notice = parse_baseband_notice(line)
    assert notice is not None
    return notice.decode()


def test_navpos_line_decodes_to_named_fields() -> None:
    record = decode(NAVPOS_LINE)
    assert record.name == "NAVPOS"
    assert record.integer("tag") == 1842461
    assert record.real("latitude") == pytest.approx(52.520645)
    assert record.real("longitude") == pytest.approx(13.409484)
    assert record.real("height") == pytest.approx(74.0)
    assert record.real("x") == pytest.approx(3783162.875)
    assert record.real("y") == pytest.approx(901938.310)
    assert record.real("z") == pytest.approx(5038321.497)


def test_navvel_line_decodes_to_values() -> None:
    record = decode(NAVVEL_LINE)
    assert record.name == "NAVVEL"
    assert record.real("value_5") == pytest.approx(-0.534)
    assert record.integer("value_6") == 18
    assert record.real("value_7") == pytest.approx(0.0)


def test_pos_result_line_decodes_to_ecef_triple() -> None:
    record = decode(POS_RESULT_LINE)
    assert record.name == "POS_RESULT"
    assert record.integer("value_1") == 478839000
    assert record.real("x") == pytest.approx(3783162.875)
    assert record.real("y") == pytest.approx(901938.310)
    assert record.real("z") == pytest.approx(5038321.497)


def test_truncated_navpos_line_is_not_a_notice() -> None:
    assert parse_baseband_notice(b"$NAVPOS,1842461,9,16\r\n") is None
    assert (
        parse_baseband_notice(
            b"$NAVPOS,1842461,9,16,1,52.52065,13.409484,74.000000,"
            b"3783162.875,901938.310,5038321.497,  20\r\n"
        )
        is None
    )


def test_solution_validates_printed_ecef() -> None:
    solution = BasebandSolution.from_record(decode(NAVPOS_LINE))
    assert solution.tag == 1842461
    assert solution.ecef_residual_m < 0.01


def test_solution_rejects_foreign_record() -> None:
    notice = parse_baseband_notice(b"$Parse TimingMode: 1\r\n")
    assert notice is not None
    with pytest.raises(ProtocolError, match="Expected a NAVPOS record"):
        BasebandSolution.from_record(notice.decode())


def test_solution_rejects_non_integer_tag() -> None:
    record = Record(
        "NAVPOS",
        (
            ("tag", "1842461"),
            ("latitude", 52.520645),
            ("longitude", 13.409484),
            ("height", 74.0),
            ("x", 3783162.875),
            ("y", 901938.310),
            ("z", 5038321.497),
        ),
    )
    with pytest.raises(ProtocolError, match="not an integer"):
        BasebandSolution.from_record(record)


def test_solution_rejects_non_finite_coordinate() -> None:
    notice = BasebandNotice(
        "NAVPOS",
        (
            "1842461",
            "9",
            "16",
            "1",
            "52.520645",
            "13.409484",
            "nan",
            "3783162.875",
            "901938.310",
            "5038321.497",
            "20",
        ),
        b"",
    )
    with pytest.raises(ProtocolError, match="non-finite"):
        BasebandSolution.from_record(notice.decode())


def test_matching_pair_separation_is_small() -> None:
    separation = solution_separation_m(decode(NAVPOS_LINE), decode(POS_RESULT_LINE))
    assert separation < 0.01


def test_separation_rejects_mismatched_names() -> None:
    position = decode(NAVPOS_LINE)
    with pytest.raises(ProtocolError, match="Expected NAVPOS and POS_RESULT"):
        solution_separation_m(position, position)


def test_solution_jump_measures_epoch_distance() -> None:
    first = BasebandSolution.from_record(decode(NAVPOS_LINE))
    moved = Record(
        "NAVPOS",
        (
            ("tag", 1842462),
            ("latitude", 52.520645),
            ("longitude", 13.409484),
            ("height", 74.0),
            ("x", 3783163.875),
            ("y", 901938.310),
            ("z", 5038321.497),
        ),
    )
    assert solution_jump_m(first, BasebandSolution.from_record(moved)) == pytest.approx(
        1.0
    )
    assert solution_jump_m(first, first) == pytest.approx(0.0)
