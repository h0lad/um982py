import pytest

from conftest import ascii_message, sentence
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareInfo, LogList
from um982py.messages import (
    BestNavigation,
    Fix,
    Heading,
    Sentence,
    Version,
)
from um982py.protocol.ascii import parse_ascii


@pytest.mark.parametrize(
    "model", [Version, BestNavigation, FirmwareInfo, LogList, Fix, Heading]
)
def test_wrong_message(
    model: type[Version]
    | type[BestNavigation]
    | type[FirmwareInfo]
    | type[LogList]
    | type[Fix]
    | type[Heading],
) -> None:
    with pytest.raises(ProtocolError):
        model.from_message(Sentence("GPRMC", (), b""))


def test_valid_and_missing_gga() -> None:
    frame = parse_ascii(
        sentence(
            b"GNGGA,120001.00,4807.038,N,01131.000,E,4,12,0.7,545.4,M,46.9,M,0.5,0123"
        )
    )
    fix = Fix.from_message(frame)
    assert fix.valid and fix.quality == 4 and fix.satellites == 12
    assert fix.latitude == pytest.approx(48.1173)
    assert fix.longitude == pytest.approx(11.5166666667)
    assert fix.altitude_msl == 545.4 and fix.geoid_separation == 46.9
    invalid = Fix.from_message(parse_ascii(b"$GNGGA,,,,,,0,,,,,,,,*78\r\n"))
    assert (
        not invalid.valid and invalid.latitude is None and invalid.altitude_msl is None
    )
    south = Fix.from_message(
        parse_ascii(sentence(b"GPGGA,1,4807.038,S,01131.000,W,1,12,1,1,M,1,M,,0"))
    )
    assert south.latitude is not None and south.latitude < 0
    assert south.longitude is not None and south.longitude < 0


@pytest.mark.parametrize(
    "latitude,hemisphere", [("4860.0", "N"), ("9100", "N"), ("NaN", "N"), ("4800", "X")]
)
def test_invalid_coordinates(latitude: str, hemisphere: str) -> None:
    frame = parse_ascii(
        sentence(
            f"GPGGA,1,{latitude},{hemisphere},01131.000,E,1,12,1,1,M,1,M,,0".encode()
        )
    )
    with pytest.raises(ProtocolError):
        Fix.from_message(frame)


def test_bad_navigation_values() -> None:
    with pytest.raises(ProtocolError):
        Fix.from_message(Sentence("GNGGA", (), b""))
    with pytest.raises(ProtocolError):
        Heading.from_message(Sentence("GPTHS", (), b""))
    for value in ("NaN", "361", "invalid"):
        with pytest.raises(ProtocolError):
            Heading.from_message(Sentence("GPTHS", (value, "A"), b""))
    assert Heading.from_message(Sentence("GPTHS", ("123.4", "A"), b"")).valid
    assert not Heading.from_message(Sentence("GPTHS", ("", "V"), b"")).valid


@pytest.mark.parametrize(
    "fields",
    [
        "2,GPGGA COM1 1,",
        "1,GPGGA BADPORT 1,",
        "1,GPGGA COM1 NaN,",
        "1,GPGGA COM1 0,",
        "1,bad,",
        "",
    ],
)
def test_invalid_loglist(fields: str) -> None:
    with pytest.raises(ProtocolError):
        LogList.from_message(parse_ascii(ascii_message("LOGLISTA", fields)))


def test_loglist_onchanged_entry() -> None:
    changed = parse_ascii(ascii_message("LOGLISTA", "1,GPSIONA COM1 ONCHANGED,"))
    assert LogList.from_message(changed).entries[0].command().text.endswith("ONCHANGED")


def test_binary_version_rejects_non_ascii_fields() -> None:
    from test_bodies import binary_message

    payload = bytearray(308)
    payload[4] = 0xFF
    with pytest.raises(ProtocolError, match="Invalid VERSION text"):
        Version.from_message(binary_message("VERSION", bytes(payload)))


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        (0, "UNKNOWN"),
        (17, "UM982"),
        (18, "UM980"),
        (19, "UM960"),
        (24, "UM960L"),
        (26, "UM981"),
        (31, "UM981S"),
        (40, "UMD982"),
        (41, "UMD981"),
        (42, "UMD981S"),
        (43, "UM981C"),
        (52, "UB9A0"),
        (53, "UBD9A0"),
        (62, "UMD960"),
        (63, "UMD980"),
        (64, "UM980C"),
        (65, "UM982C"),
        (999, "999"),
    ],
)
def test_binary_version_model_ids(model_id: int, expected: str) -> None:
    from struct import pack_into

    from test_bodies import binary_message

    payload = bytearray(308)
    pack_into("<I", payload, 0, model_id)
    assert (
        Version.from_message(binary_message("VERSION", bytes(payload))).model
        == expected
    )
