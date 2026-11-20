"""Verify the experimental native Doppler velocity layout."""

from struct import pack_into

import pytest

from test_protocol import binary
from um982py.commands.types import Port
from um982py.errors import ProtocolError
from um982py.experimental import (
    decode_velocity_data,
    velocity_data_output,
    velocity_data_read,
    velocity_data_stop,
)
from um982py.messages import Message
from um982py.protocol import StreamDecoder


def _frame(payload: bytes, message_id: int = 95) -> Message:
    (message,) = StreamDecoder(strict=True).feed(binary(payload, message_id=message_id))
    return message


def test_velocity_data_uses_native_vector_and_payload_epoch() -> None:
    payload = bytearray(120)
    pack_into("<HHI", payload, 0, 2445, 65535, 463976125)
    pack_into("<4d", payload, 16, -0.005, 0.008, -0.006, 8.0)
    pack_into("<3d", payload, 48, 0.3, 0.4, 1.2)
    message = _frame(bytes(payload))
    command = velocity_data_read(port=Port.COM2)
    assert command.matches(message)
    velocity = command.decode(message)
    assert velocity.message is message
    assert velocity.gps_week == 2445
    assert velocity.milliseconds_of_week == 463976125
    assert velocity.epoch_gps_seconds == 2445 * 604800 + 463976.125
    assert velocity.velocity_ecef_mps == (-0.005, 0.008, -0.006)
    assert velocity.uncertainty_3d_mps == pytest.approx(1.3)
    assert command.text == "VELDATAB COM2"
    assert velocity_data_output(port=Port.COM2).text == "VELDATAB COM2 1"
    assert velocity_data_output(rate_hz=5).text == "VELDATAB 0.2"
    assert velocity_data_stop(port=Port.COM2).text == "UNLOG COM2 VELDATAB"


@pytest.mark.parametrize(
    ("format_code", "offset", "value", "error"),
    [
        ("<I", 4, 604800000, "milliseconds of week"),
        ("<d", 24, float("nan"), "velocity"),
        ("<d", 48, -1.0, "uncertainty"),
        ("<d", 64, float("inf"), "uncertainty"),
    ],
)
def test_invalid_velocity_data(
    format_code: str, offset: int, value: float, error: str
) -> None:
    payload = bytearray(120)
    pack_into(format_code, payload, offset, value)
    with pytest.raises(ProtocolError, match=error):
        decode_velocity_data(_frame(bytes(payload)))


def test_velocity_data_requires_exact_binary_layout() -> None:
    with pytest.raises(ProtocolError, match="ID 95"):
        decode_velocity_data(_frame(bytes(120), 99))
    for length in (119, 121):
        with pytest.raises(ProtocolError, match="body length"):
            decode_velocity_data(_frame(bytes(length)))
