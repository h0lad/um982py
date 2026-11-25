"""Alternative renderings of documented solutions and navigation data."""

import math
from dataclasses import replace

import pytest

from conftest import FIXTURES
from um982py.commands import Log, Trigger
from um982py.errors import ProtocolError
from um982py.experimental import (
    decode_matched_position,
    matched_baseline,
    matched_position_output,
    matched_position_read,
)
from um982py.geodesy import geodetic_from_ecef
from um982py.messages import AsciiMessage, BinaryMessage, decode_log
from um982py.messages.layouts import LAYOUTS
from um982py.protocol import StreamDecoder
from um982py.signals import tracking_signal

VARIANTS = FIXTURES / "captures-variants"
POSITIONS = (Log.PSRPOS2, Log.RTKPOS2, Log.PPPPOS, Log.MPPPPOS)
NAVIGATION = (Log.MPPPDOP, Log.BD2EPHEM, Log.BD3B2AEPHEM, Log.BD3IONUTC)
EPHEMERIS_COPIES = {
    Log.GPSEPHEM: "GPSEPH",
    Log.GPSEPHEMERIS: "GPSEPH",
    Log.BDSEPHEM: "BDSEPH",
    Log.GALEPHEM: "GALEPH",
    Log.GALEPHEMERIS: "GALEPH",
    Log.GLOEPHEM: "GLOEPH",
    Log.GLOEPHEMERIS: "GLOEPH",
}
ALMANAC_AND_PACKINGS = (Log.ALMANAC, Log.BDSEPHEMERIS, Log.BD3EPHEM)
FORMATS = [
    (log, binary)
    for log in (
        *POSITIONS,
        *NAVIGATION,
        *EPHEMERIS_COPIES,
        *ALMANAC_AND_PACKINGS,
        Log.BASESTATION,
    )
    for binary in (False, True)
    if binary or log is not Log.BASESTATION
]


def captured(log: Log, binary: bool) -> AsciiMessage | BinaryMessage:
    folder = FIXTURES / "captures" if log is Log.BESTPOS else VARIANTS
    raw = (folder / (log.wire_name(binary=binary) + ".bin")).read_bytes()
    (message,) = (
        m
        for m in StreamDecoder(strict=True).feed(raw)
        if isinstance(m, (AsciiMessage, BinaryMessage))
    )
    return message


@pytest.mark.parametrize("log,binary", FORMATS)
def test_live_variant_captures_decode(log: Log, binary: bool) -> None:
    message = captured(log, binary)
    record = log.decode(message)
    assert record.name == log.value and record.message is message
    assert log.read(binary=binary).decode(message) == record
    assert decode_log(message) == record


@pytest.mark.parametrize("log,binary", FORMATS)
def test_variant_captures_reject_truncated_and_extra_fields(
    log: Log, binary: bool
) -> None:
    message = captured(log, binary)
    if isinstance(message, BinaryMessage):
        bad = [
            replace(message, payload=message.payload[:-1]),
            replace(message, payload=message.payload + b"\0"),
        ]
    else:
        bad = [
            replace(message, fields=message.fields[:-1]),
            replace(message, fields=(*message.fields, "extra")),
        ]
    for changed in bad:
        with pytest.raises(ProtocolError):
            log.decode(changed)


@pytest.mark.parametrize("log", POSITIONS)
def test_position_variants_use_the_bestpos_layout(log: Log) -> None:
    expected = list(Log.BESTPOS.decode(captured(Log.BESTPOS, True)))
    for binary in (False, True):
        assert list(log.decode(captured(log, binary))) == expected


def test_position_variants_report_their_solution_types() -> None:
    assert Log.PSRPOS2.decode(captured(Log.PSRPOS2, False))["pos_type"] == "SBAS"
    assert Log.PSRPOS2.decode(captured(Log.PSRPOS2, True)).integer("pos_type") == 18
    for log in (Log.PPPPOS, Log.MPPPPOS):
        assert log.decode(captured(log, False))["pos_type"] == "PPP_CONVERGING"
        assert log.decode(captured(log, True)).integer("pos_type") == 68
    empty = Log.RTKPOS2.decode(captured(Log.RTKPOS2, True))
    assert empty.real("lat") == empty.real("lon") == 0.0


@pytest.mark.parametrize("log", (Log.MPPPPOS, Log.MPPPDOP))
def test_matched_ppp_logs_are_onchanged_only(log: Log) -> None:
    assert log.definition.changed_only
    assert log.output(Trigger.ON_CHANGED, binary=True).text == (
        f"{log.wire_name(binary=True)} ONCHANGED"
    )
    with pytest.raises(ValueError, match="requires ONCHANGED"):
        log.output(1, binary=True)


def test_matched_ppp_dop_lists_its_satellites() -> None:
    for binary in (False, True):
        record = Log.MPPPDOP.decode(captured(Log.MPPPDOP, binary))
        assert record.integer("count_prn") == 5
        assert record["prn"] == (25, 32, 79, 87, 90)
        assert record.real("gdop") == pytest.approx(5.299, abs=1e-3)
        assert record.real("cutoff") == 7.0


def test_bd2ephem_is_the_bdseph_record() -> None:
    names = [field.name for field in LAYOUTS["BDSEPH"].fields]
    for binary in (False, True):
        record = Log.BD2EPHEM.decode(captured(Log.BD2EPHEM, binary))
        assert list(record) == names
        assert record.integer("prn") == 8
        assert record.real("toe") == 309_600.0
        assert record.real("a") == pytest.approx(4.215915018e7)


def test_bd3b2aephem_carries_the_b1c_and_b2a_group_delays() -> None:
    ascii_record = Log.BD3B2AEPHEM.decode(captured(Log.BD3B2AEPHEM, False))
    binary_record = Log.BD3B2AEPHEM.decode(captured(Log.BD3B2AEPHEM, True))
    for record in (ascii_record, binary_record):
        assert record.integer("prn") == 8
        assert record.real("toe") == record.real("toc") == 309_600.0
        assert record.real("deltaa") == pytest.approx(-2852.818359)
        assert record.real("tgdb1cp") == pytest.approx(2.502929419e-9)
        assert record.real("tgdb2ap") == pytest.approx(-8.032657206e-9)
        assert record.real("iscb2ad") == pytest.approx(-2.735760063e-9)
        assert record.real("af0") == pytest.approx(-2.910046023e-4)
        assert record.integer("itop") == 1030
        assert record.integer("freqtype") == 0
    for (name, value), (_, other) in zip(
        ascii_record.entries, binary_record.entries, strict=True
    ):
        assert value == pytest.approx(other, rel=1e-9), name


def test_bd3ionutc_combines_the_bdgim_and_utc_parameters() -> None:
    for binary in (False, True):
        record = Log.BD3IONUTC.decode(captured(Log.BD3IONUTC, binary))
        assert tuple(record.real(f"a{index}") for index in range(1, 10)) == (
            20.0,
            -3.5,
            7.5,
            4.875,
            -7.375,
            0.25,
            -0.5,
            1.75,
            0.75,
        )
        assert record.real("utc_a0") == pytest.approx(-2.619344741e-10)
        assert record.integer("utc_wn") == 1090
        assert record.integer("wn_lsf") == 573
        assert (record.integer("deltat_ls"), record.integer("deltat_lsf")) == (4, 4)
        assert record.integer("dn") == 6


def test_basestation_holds_primary_antenna_observations() -> None:
    record = Log.BASESTATION.decode(captured(Log.BASESTATION, True))
    assert record.integer("week") == 2446
    assert record["station_name"] == "UNICORE"
    latitude, longitude, _ = geodetic_from_ecef(
        record.real("p_x"), record.real("p_y"), record.real("p_z")
    )
    assert 52.2 < latitude < 52.8 and 13.0 < longitude < 13.8
    slots = record.records("observations")
    used = [slot for slot in slots if slot.real("pseudorange") > 0]
    assert len(slots) == 240
    assert len(used) == 82
    first = used[0]
    signal = tracking_signal(first.integer("tracking_status"))
    assert signal is not None and signal.constellation == "GPS"
    assert 1.9e7 < first.real("pseudorange") < 2.6e7


@pytest.mark.parametrize("log", list(EPHEMERIS_COPIES))
def test_ephemeris_copies_use_the_documented_layout(log: Log) -> None:
    names = [field.name for field in LAYOUTS[EPHEMERIS_COPIES[log]].fields]
    for binary in (False, True):
        record = log.decode(captured(log, binary))
        assert list(record) == names


def test_bdsephemeris_is_bdseph_with_the_square_root_of_a() -> None:
    reference = Log.BD2EPHEM.decode(captured(Log.BD2EPHEM, True))
    for binary in (False, True):
        record = Log.BDSEPHEMERIS.decode(captured(Log.BDSEPHEMERIS, binary))
        assert record.integer("prn") == reference.integer("prn") == 8
        assert record.integer("week") == 1090
        assert record.real("sqrt_a") ** 2 == pytest.approx(reference.real("a"))
        for name in ("ecc", "omega_0", "i0", "crc", "cis", "af0"):
            assert record.real(name) == pytest.approx(reference.real(name)), name


def test_bd3ephem_adds_one_word_to_the_b2a_packing() -> None:
    reference = Log.BD3B2AEPHEM.decode(captured(Log.BD3B2AEPHEM, True))
    record = Log.BD3EPHEM.decode(captured(Log.BD3EPHEM, True))
    assert list(record) == [*reference, "field_43"]
    assert record.integer("field_43") == 1
    for name in ("prn", "toe", "deltaa", "tgdb1cp", "iscb2ad", "af0"):
        assert record[name] == reference[name], name


def test_almanac_page_is_a_gps_almanac() -> None:
    ascii_record = Log.ALMANAC.decode(captured(Log.ALMANAC, False))
    binary_record = Log.ALMANAC.decode(captured(Log.ALMANAC, True))
    for record in (ascii_record, binary_record):
        assert record.integer("prn") == 1
        assert record.integer("week") == 2446
        assert record.real("a") == pytest.approx(2.6560404e7)
        inclination = 0.3 * math.pi + record.real("inclination_offset")
        assert math.degrees(inclination) == pytest.approx(54.75, abs=0.01)
        assert record.real("mean_motion") == pytest.approx(
            math.sqrt(3.986005e14 / record.real("a") ** 3), rel=1e-4
        )
        assert record.integer("health_prn") == record.integer("health_almanac") == 0
    assert ascii_record["antispoof"] == "TRUE"
    assert binary_record["antispoof"] == 1


def test_matched_position_reads_the_secondary_antenna() -> None:
    for binary in (False, True):
        record = decode_matched_position(
            captured_variant("MATCHEDPOSH" + ("B" if binary else "A"))
        )
        assert record.name == "MATCHEDPOSH"
        assert list(record) == list(Log.BESTPOS.decode(captured(Log.BESTPOS, True)))
    assert matched_position_read(antenna=2).text == "MATCHEDPOSHB"
    assert matched_position_output(antenna="secondary").text == (
        "MATCHEDPOSHB ONCHANGED"
    )
    assert matched_position_read().text == "MATCHEDPOSB"


def test_matched_baseline_reproduces_the_heading_vector() -> None:
    base = Log.BASESTATION.decode(captured(Log.BASESTATION, True))
    rover = decode_matched_position(captured_variant("MATCHEDPOSHB"))
    baseline = matched_baseline(base, rover)
    assert baseline.length_m == pytest.approx(3.9866, abs=1e-4)
    assert math.dist(baseline.ecef_m, (0.0, 0.0, 0.0)) == pytest.approx(
        baseline.length_m
    )
    east, north, _ = baseline.enu_m
    assert baseline.heading_deg == pytest.approx(
        math.degrees(math.atan2(east, north)) % 360
    )
    assert baseline.pitch_deg == pytest.approx(-51.60, abs=0.01)
    with pytest.raises(ValueError):
        matched_baseline(rover, base)


def captured_variant(name: str) -> AsciiMessage | BinaryMessage:
    raw = (VARIANTS / f"{name}.bin").read_bytes()
    (message,) = (
        m
        for m in StreamDecoder(strict=True).feed(raw)
        if isinstance(m, (AsciiMessage, BinaryMessage))
    )
    return message
