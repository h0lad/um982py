"""Check Unicore binary messages generated independently by pyunigps 1.0.1."""

import pytest

from um982py.messages import decode_log
from um982py.protocol.binary import parse_binary


@pytest.mark.parametrize(
    ("name", "wire_hex", "expected"),
    [
        (
            "GPSION",
            "aa44b50008004c000000600978e001000000000000120000"
            "000000000000f43f000000000000e0bf0000000000000000"
            "0000000000000000000000000000c0400000000000000000"
            "000000000000000000000000000000000000600900000000"
            "0000000034398f2e",
            {"a0": 1.25, "a1": -0.5, "b0": 8192.0, "usweek": 2400},
        ),
        (
            "BESTNAV",
            "aa44b500460878000000600978e001000000000000120000"
            "00000000100000000000000000404a40cdcccccccccc2a40"
            "0000000000004e4000000000000000000000000000000000"
            "000000002020202000000000000000001611000000000000"
            "000000000000000000000000000000000000000000000c40"
            "000000000000000000000000000000000000000000000000"
            "4b546816",
            {
                "pos_type": 16,
                "lat": 52.5,
                "lon": 13.4,
                "hgt": 60.0,
                "count_svs": 22,
                "count_solnsvs": 17,
                "hor_spd": 3.5,
            },
        ),
        (
            "TROPINFO",
            "aa44b5000e0918000000600978e001000000000000120000"
            "0200000000002040000000400000003f0000000000000000"
            "190cc11e",
            {"trop_module": 2, "tropzenith": 2.5, "dry": 2.0, "wet": 0.5},
        ),
        (
            "FREQJAMSTATUS",
            "aa44b50007020c000000600978e001000000000000120000"
            "100000001e010c00050000007a3de712",
            {"pos_type": 16, "l1cwratio": 30, "l1cwflag": 1, "l2cwratio": 12},
        ),
    ],
)
def test_pyunigps_generated_unicore_messages(
    name: str, wire_hex: str, expected: dict[str, int | float]
) -> None:
    message = parse_binary(bytes.fromhex(wire_hex))
    record = decode_log(message)

    assert record.name == name
    assert message.header.week == 2400
    assert message.header.milliseconds == 123000
    for field, value in expected.items():
        assert record[field] == pytest.approx(value)
