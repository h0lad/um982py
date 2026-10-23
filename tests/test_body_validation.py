from dataclasses import replace
from struct import pack

import pytest

from test_bodies import binary_message, manual_message
from um982py.errors import ProtocolError
from um982py.messages import (
    AsciiMessage,
    LegacyAsciiHeader,
    LogListMessage,
    Observation,
    Record,
    Sentence,
    decode_log,
)
from um982py.messages.corrections import (
    Availability,
    has_clock_multiplier,
    has_correction,
    has_signal_indices,
    has_signal_name,
    has_validity_seconds,
    mask_indices,
)
from um982py.messages.enums import (
    AssistedStatus,
    EventStatus,
    HardwareFlags,
    HasBlocks,
    MessageSatelliteSystem,
    PositionType,
    SatelliteSystem,
    SolutionStatus,
)


def test_enumerations() -> None:
    assert PositionType.NARROW_INT == 50
    assert PositionType.PPP == 69
    assert PositionType.PPP_AR == 70
    assert PositionType.PPP_RTK == 71
    assert SolutionStatus.SOL_COMPUTED == 0
    assert SolutionStatus.SINGULARITY == 3
    assert SatelliteSystem.GALILEO == 3
    assert (
        EventStatus(11)
        == EventStatus.SECONDS_VALID | EventStatus.PPS_VALID | EventStatus.WEEK_VALID
    )
    assert HardwareFlags(0x99) & HardwareFlags.EXTERNAL_CLOCK
    assert HasBlocks(50) == HasBlocks.MASK | HasBlocks.ORBIT | HasBlocks.CODE_BIAS
    assert AssistedStatus(15) & AssistedStatus.POSITION_VALID


@pytest.mark.parametrize(
    "kind,raw,meters",
    [
        ("radial", 100, 0.25),
        ("in_track", -100, -0.8),
        ("cross_track", 100, 0.8),
        ("clock", 100, 0.25),
        ("code", 100, 0.25),
        ("phase", -100, -1),
    ],
)
def test_has_units(kind: str, raw: int, meters: float) -> None:
    from typing import Literal, cast

    correction = has_correction(
        raw,
        cast(
            Literal["radial", "in_track", "cross_track", "clock", "code", "phase"], kind
        ),
    )
    assert correction.meters == meters
    assert correction.availability is Availability.AVAILABLE


def test_has_availability_and_masks() -> None:
    assert [has_clock_multiplier(code) for code in range(4)] == [1, 2, 3, 4]
    assert has_signal_indices(0x8140) == (0, 7, 9)
    assert [has_signal_name(0, i) for i in has_signal_indices(0x8140)] == [
        "L1 C/A",
        "L2 CL",
        "L2 P",
    ]
    assert has_signal_name(2, 12) == "E6-B C/NAV HAS"
    assert has_signal_name(0, 1) is None
    assert has_signal_name(1, 0) is None
    with pytest.raises(ValueError):
        has_signal_indices(65536)
    with pytest.raises(ValueError):
        has_signal_name(2, 16)
    with pytest.raises(ValueError):
        has_clock_multiplier(4)
    assert has_correction(-4096, "clock").availability is Availability.UNAVAILABLE
    assert has_correction(4095, "clock").availability is Availability.DO_NOT_USE
    assert has_correction(-4096, "radial").meters is None
    assert has_correction(-1024, "phase").meters is None
    assert has_correction(100, "clock", multiplier=4).meters == 1
    assert has_validity_seconds(0) == 5
    assert has_validity_seconds(14) == 3600
    assert has_validity_seconds(15) is None
    assert mask_indices(b"\x80\x01") == (0, 15)
    assert mask_indices(b"") == ()
    for value in (-1, 16, True):
        with pytest.raises(ValueError):
            has_validity_seconds(value)
    with pytest.raises(ValueError):
        has_correction(4096, "radial")
    with pytest.raises(ValueError):
        has_correction(True, "radial")
    with pytest.raises(ValueError):
        has_correction(1, "code", multiplier=True)
    with pytest.raises(ValueError):
        has_correction(1, "code", multiplier=2)


def test_missing_and_malformed_body_fields() -> None:
    with pytest.raises(ProtocolError):
        decode_log(binary_message("VERSION", b"\0" * 4 + b"\xff" * 304))
    with pytest.raises(ProtocolError):
        decode_log(binary_message("GPSION", pack("<d", float("nan")) + b"\0" * 68))
    for name, value in (
        ("GPSIONA", "nan"),
        ("BESTSATA", "1+bad"),
        ("PPPB2BINFO1A", "00"),
    ):
        message = manual_message(name)
        assert isinstance(message, AsciiMessage)
        fields = list(message.fields)
        fields[{"GPSIONA": 0, "BESTSATA": 2, "PPPB2BINFO1A": 4}[name]] = value
        with pytest.raises(ProtocolError):
            decode_log(replace(message, fields=tuple(fields)))
    with pytest.raises(ProtocolError):
        decode_log(binary_message("INFOPART1", b"\x01\x01\x81\0" + b"x" * 129))
    with pytest.raises(ProtocolError):
        decode_log(binary_message("INFOPART1", b"\x09"))
    message = manual_message("OBSVHA")
    assert isinstance(message, AsciiMessage)
    with pytest.raises(ProtocolError):
        decode_log(replace(message, fields=("",)))


def test_empty_prn_list() -> None:
    message = manual_message("STADOPA")
    assert isinstance(message, AsciiMessage)
    record = decode_log(replace(message, fields=(*message.fields[:10], "0", "")))
    assert record["prn"] == ()


def test_satellite_frequency_consistency() -> None:
    header = b"\x01\x02\0\0\0\x3f"
    satellite = b"\x02\0\0\x3c"
    for frequencies in (b"\0\x2a\0\0", b"\0\x2a\0\x02\0\x2a\x09\x03"):
        with pytest.raises(ProtocolError):
            decode_log(binary_message("SATSINFO", header + satellite + frequencies))


def test_nmea_invalid_values_and_legacy_options() -> None:
    with pytest.raises(ProtocolError):
        decode_log(Sentence("GPUNKNOWN", (), b""))
    message = manual_message("GNGGA")
    assert isinstance(message, Sentence)
    with pytest.raises(ProtocolError):
        decode_log(
            replace(message, fields=(message.fields[0], "9060", *message.fields[2:]))
        )
    with pytest.raises(ProtocolError):
        decode_log(Sentence("GPGSV", ("2", "1", "5", *(["1"] * 20)), b""))
    message = manual_message("GNRMC")
    assert isinstance(message, Sentence)
    record = decode_log(replace(message, fields=message.fields[:-1]))
    assert record["navigation_status"] is None
    message = manual_message("GPGSV")
    assert isinstance(message, Sentence)
    record = decode_log(replace(message, fields=message.fields[:-1]))
    assert record["signal_id"] is None
    with pytest.raises(TypeError):
        Record("bad", (("items", (1,)),)).records("items")


def test_unknown_binary_id() -> None:
    message = binary_message("GPSION", bytes(76))
    with pytest.raises(ProtocolError):
        decode_log(replace(message, header=replace(message.header, message_id=65535)))


@pytest.mark.parametrize(
    "entry",
    [
        "bad",
        "GPGGA COM4 1",
        "GPGGA COM1 nan",
        "GPGGA COM1 0",
        "LOG COM1 GPGGA INVALID 1",
    ],
)
def test_invalid_log_list_entry(entry: str) -> None:
    with pytest.raises(ProtocolError):
        decode_log(LogListMessage(LegacyAsciiHeader("UNILOGLIST", ()), (entry,), b""))


@pytest.mark.parametrize(
    "entry",
    ["LOG COM1 GPGGA ONTIME 1", "GPGGA COM1 ONCHANGED", "LOG COM2 VERSIONA ONCE 0"],
)
def test_log_list_trigger_forms(entry: str) -> None:
    record = decode_log(
        LogListMessage(LegacyAsciiHeader("UNILOGLIST", ()), (entry,), b"")
    )
    assert len(record.records("logs")) == 1


def test_zero_compressed_doppler() -> None:
    observation = Observation.from_record(
        Record("observation", (("cmp_record", bytes(24)),))
    )
    assert observation.doppler_hz == 0
    assert observation.glonass_frequency is None


@pytest.mark.parametrize("channel", [-2, 8])
def test_satellite_glonass_id_in_ascii_and_binary(channel: int) -> None:
    message = manual_message("SATELLITEA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[0], fields[4] = "GLONASS", f"42{channel:+d}"
    ascii_record = decode_log(replace(message, fields=tuple(fields)))
    binary = pack("<IIIIHhIdddd", 1, 1, 1, 1, 42, channel, 0, 25.2, 308.1, 0.0, 0.0)
    binary_record = decode_log(binary_message("SATELLITE", binary))
    for record in (ascii_record, binary_record):
        satellite_id = record.records("satellites")[0]["prn_slot"]
        assert isinstance(satellite_id, Record)
        assert satellite_id.integer("prn") == 42
        assert satellite_id.integer("channel") == channel


@pytest.mark.parametrize(
    ("number", "label"),
    [
        (0, "GPS"),
        (1, "GLONASS"),
        (2, "SBAS"),
        (5, "GALILEO"),
        (6, "BEIDOU"),
        (7, "QZSS"),
        (9, "NAVIC"),
    ],
)
def test_message_satellite_systems_match_ascii_and_binary(
    number: int, label: str
) -> None:
    satellite = MessageSatelliteSystem.from_wire(number)
    assert satellite is MessageSatelliteSystem.from_wire(label)
    assert satellite.name == label


def test_message_systems_are_distinct_from_tracking_status_codes() -> None:
    assert MessageSatelliteSystem.from_wire(5).name == "GALILEO"
    assert SatelliteSystem(5).name == "QZSS"
    for value in (3, 4, 8, True, "UNKNOWN"):
        with pytest.raises(ValueError):
            MessageSatelliteSystem.from_wire(value)


def test_message_system_from_decoded_bestsat() -> None:
    message = manual_message("BESTSATA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[1] = "GALILEO"
    ascii_record = decode_log(replace(message, fields=tuple(fields)))
    binary_record = decode_log(
        binary_message("BESTSAT", pack("<IIHhII", 1, 5, 4, 0, 0, 3))
    )
    for record in (ascii_record, binary_record):
        value = record.records("satellites")[0]["satellite_system"]
        assert isinstance(value, (int, str))
        assert MessageSatelliteSystem.from_wire(value) is MessageSatelliteSystem.GALILEO
