"""Alternative renderings of documented solutions and navigation data."""

from dataclasses import replace

import pytest

from conftest import FIXTURES
from um982py.commands import Log, Trigger
from um982py.errors import ProtocolError
from um982py.geodesy import geodetic_from_ecef
from um982py.messages import AsciiMessage, BinaryMessage, decode_log
from um982py.messages.layouts import LAYOUTS
from um982py.protocol import StreamDecoder
from um982py.signals import tracking_signal

VARIANTS = FIXTURES / "captures-variants"
POSITIONS = (Log.PSRPOS2, Log.RTKPOS2, Log.PPPPOS, Log.MPPPPOS)
NAVIGATION = (Log.MPPPDOP, Log.BD2EPHEM, Log.BD3B2AEPHEM, Log.BD3IONUTC)
FORMATS = [
    (log, binary)
    for log in (*POSITIONS, *NAVIGATION, Log.BASESTATION)
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
    assert len(used) == 84
    first = used[0]
    signal = tracking_signal(first.integer("tracking_status"))
    assert signal is not None and signal.constellation == "GPS"
    assert 1.9e7 < first.real("pseudorange") < 2.6e7
