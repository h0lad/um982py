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
