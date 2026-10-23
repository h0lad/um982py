"""Check coordinate and RTCM reference-message boundaries."""

from datetime import UTC, datetime

from examples.ntrip_client import ReferenceStation, gga_from_fix

from um982py.messages.navigation import Fix
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import parse_rtcm
from um982py.protocol.checksums import rtcm_crc24q


def test_gga_rounding_carries_into_next_degree() -> None:
    fix = Fix("", 48.999999999, -9.999999999, 1, 12, 0.8, 100, 45, None, "")
    gga = gga_from_fix(fix, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert parse_ascii(gga).fields[1:5] == ("4900.000000", "N", "01000.000000", "W")


def test_station_frame_requires_correct_length_for_message_type() -> None:
    for kind, length in ((1005, 21), (1006, 19)):
        payload = (kind << (length * 8 - 12)).to_bytes(length, "big")
        body = b"\xd3\x00" + bytes([length]) + payload
        message = parse_rtcm(body + rtcm_crc24q(body).to_bytes(3, "big"))
        assert ReferenceStation.from_rtcm(message) is None
