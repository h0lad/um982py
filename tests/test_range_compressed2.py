import pytest

from test_protocol import binary
from um982py.errors import ProtocolError
from um982py.experimental import (
    decode_rangecmp2,
    rangecmp2_output,
    rangecmp2_read,
    rangecmp2_stop,
)
from um982py.protocol.binary import parse_binary


@pytest.mark.parametrize(
    "antenna,message_id,name",
    [
        (1, 1273, "RANGECMP2B"),
        (2, 2112, "RANGECMP2HB"),
    ],
)
def test_native_compressed_blocks(antenna: int, message_id: int, name: str) -> None:
    header = (2 << 76) | (20_000_000 << 26) | (7 << 8)
    l1 = (0xFFFFF << 59) | (56 << 45) | 0x81
    l2 = (1024 << 59) | 0x24
    other = (14_000_000 << 26) | (3 << 20) | (11 << 8)
    body = (
        header.to_bytes(10, "little")
        + l1.to_bytes(12, "little")
        + l2.to_bytes(12, "little")
        + other.to_bytes(10, "little")
    )
    message = parse_binary(binary(len(body).to_bytes(4, "little") + body, message_id))
    request = rangecmp2_read(antenna=antenna)
    assert request.text == name
    assert request.matches(message)
    assert rangecmp2_output(0.2, antenna=antenna).text == f"{name} 0.2"
    assert rangecmp2_stop(antenna=antenna).text == f"UNLOG {name}"
    frame = decode_rangecmp2(message)
    assert frame.message is message
    assert frame.antenna == antenna
    gps, galileo = frame.satellites
    assert (gps.prn, gps.system, gps.range_base_m) == (7, 0, 20_000_000)
    assert (galileo.prn, galileo.system, galileo.signals) == (11, 3, ())
    first, second = gps.signals
    assert (first.signal_type, first.pseudorange_offset_m) == (1, 56 / 128)
    assert first.code_locked and first.phase_at_ceiling and not first.phase_locked
    assert (
        second.phase_locked and not second.phase_at_ceiling and not second.code_locked
    )
    assert second.signal_type == 4
    assert second.phase_offset_m == 0.5


@pytest.mark.parametrize(
    "body,message_id,error",
    [
        (b"", 1273, "body length"),
        (bytes(5), 1273, "body length"),
        (b"\x01" + bytes(4), 1273, "satellite block"),
        (b"\x0a" + bytes(12) + b"\x10", 1273, "signal block"),
        (bytes(4), 43, "binary RANGECMP2"),
    ],
)
def test_invalid_native_compressed_blocks(
    body: bytes, message_id: int, error: str
) -> None:
    with pytest.raises(ProtocolError, match=error):
        decode_rangecmp2(parse_binary(binary(body, message_id)))
