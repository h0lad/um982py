"""BESTNAV direct models reject invalid numeric coordinates and velocities."""

from dataclasses import replace
from struct import pack_into

import pytest

from test_bodies import binary_message, manual_message
from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, BestNavigation


@pytest.mark.parametrize(
    ("index", "value"), [(2, "nan"), (3, "181"), (4, "inf"), (25, "nan"), (27, "-inf")]
)
def test_ascii_bestnav_rejects_bad_numeric_values(index: int, value: str) -> None:
    message = manual_message("BESTNAVA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[index] = value
    with pytest.raises(ProtocolError):
        BestNavigation.from_message(replace(message, fields=tuple(fields)))


@pytest.mark.parametrize(
    ("offset", "value"),
    [
        (8, float("nan")),
        (16, 181.0),
        (24, float("inf")),
        (88, float("nan")),
        (104, float("-inf")),
    ],
)
def test_binary_bestnav_rejects_bad_numeric_values(offset: int, value: float) -> None:
    data = bytearray(120)
    pack_into("<d", data, offset, value)
    with pytest.raises(ProtocolError):
        BestNavigation.from_message(binary_message("BESTNAV", bytes(data)))


def test_ascii_position_and_velocity_have_independent_validity() -> None:
    message = manual_message("BESTNAVA")
    assert isinstance(message, AsciiMessage)
    navigation = BestNavigation.from_message(message)
    assert navigation.valid and navigation.velocity_valid
    assert navigation.datum == "WGS84"
    assert navigation.ellipsoidal_height == pytest.approx(57.3387)

    fields = list(message.fields)
    fields[21] = "INSUFFICIENT_OBS"
    navigation = BestNavigation.from_message(replace(message, fields=tuple(fields)))
    assert navigation.valid and not navigation.velocity_valid

    fields[0] = "INSUFFICIENT_OBS"
    fields[21] = "SOL_COMPUTED"
    navigation = BestNavigation.from_message(replace(message, fields=tuple(fields)))
    assert not navigation.valid and navigation.velocity_valid

    fields[0] = "SOL_COMPUTED"
    fields[1] = "UNKNOWN_TYPE"
    fields[22] = "NONE"
    navigation = BestNavigation.from_message(replace(message, fields=tuple(fields)))
    assert not navigation.valid and not navigation.velocity_valid

    fields[1] = "DOPPLER_VELOCITY"
    navigation = BestNavigation.from_message(replace(message, fields=tuple(fields)))
    assert not navigation.valid


def test_binary_position_and_velocity_have_independent_validity() -> None:
    payload = bytearray(120)
    pack_into("<II", payload, 0, 0, 16)
    pack_into("<II", payload, 72, 1, 8)
    navigation = BestNavigation.from_message(binary_message("BESTNAV", bytes(payload)))
    assert navigation.valid and not navigation.velocity_valid

    pack_into("<II", payload, 0, 1, 16)
    pack_into("<II", payload, 72, 0, 8)
    navigation = BestNavigation.from_message(binary_message("BESTNAV", bytes(payload)))
    assert not navigation.valid and navigation.velocity_valid

    pack_into("<II", payload, 0, 0, 9999)
    pack_into("<II", payload, 72, 0, 9999)
    navigation = BestNavigation.from_message(binary_message("BESTNAV", bytes(payload)))
    assert not navigation.valid and not navigation.velocity_valid


def test_position_standard_deviations_from_ascii_and_binary() -> None:
    message = manual_message("BESTNAVA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[7:10] = ["0.12", "0.34", "0.56"]
    ascii_nav = BestNavigation.from_message(replace(message, fields=tuple(fields)))

    payload = bytearray(120)
    pack_into("<fff", payload, 40, 0.12, 0.34, 0.56)
    binary_nav = BestNavigation.from_message(binary_message("BESTNAV", bytes(payload)))
    for navigation in (ascii_nav, binary_nav):
        assert navigation.latitude_std_m == pytest.approx(0.12)
        assert navigation.longitude_std_m == pytest.approx(0.34)
        assert navigation.height_std_m == pytest.approx(0.56)


def test_unavailable_position_standard_deviations() -> None:
    message = manual_message("BESTNAVA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[7:10] = ["", "-1", "nan"]
    ascii_nav = BestNavigation.from_message(replace(message, fields=tuple(fields)))

    payload = bytearray(120)
    pack_into("<fff", payload, 40, float("inf"), -1, float("nan"))
    binary_nav = BestNavigation.from_message(binary_message("BESTNAV", bytes(payload)))
    for navigation in (ascii_nav, binary_nav):
        assert navigation.latitude_std_m is None
        assert navigation.longitude_std_m is None
        assert navigation.height_std_m is None
