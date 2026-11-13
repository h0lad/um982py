"""R1.16 tables and the newly documented receiver logs."""

from dataclasses import replace
from struct import pack_into
from typing import cast

import pytest

from test_extended_logs import captured
from um982py.commands import Log, configuration, masking
from um982py.messages import AsciiMessage, BinaryMessage
from um982py.protocol import StreamDecoder


def test_r116_ppsstatus_manual_example() -> None:
    raw = (
        b"#PPSSTATUSA,88,GPS,FINE,2274,116752000,0,0,18,30;"
        b"3,2274,116751000,5,48100295,0x03E80020,0x00000015,2,"
        b"0x00466669,0x2B000000,0x0110D2BC,0x00000000,0xD3516B6C,"
        b"0x00000000,0x00000000*621e1925\r\n"
    )
    message = next(
        m for m in StreamDecoder(strict=True).feed(raw) if isinstance(m, AsciiMessage)
    )
    record = Log.PPSSTATUS.decode(message)
    assert record.integer("status") == 3
    assert record.integer("gps_week") == 2274
    assert record.integer("milliseconds_of_week") == 116751000
    assert record.integer("pulse_error_ns") == 5
    assert record.integer("observation_offset_0_01_ns") == 48100295
    assert record.integer("config_info") == 0x03E80020
    assert record.integer("pps_config_status") == 0x0110D2BC
    assert record["gps_week"] == record["field_02"]
    binary = cast(BinaryMessage, captured(Log.PPSSTATUS, True))
    payload = bytearray(binary.payload)
    pack_into("<i", payload, 12, -123)
    pack_into("<I", payload, 32, 0xFFFFFFFF)
    decoded = Log.PPSSTATUS.decode(replace(binary, payload=bytes(payload)))
    assert decoded.integer("pulse_error_ns") == -123
    assert decoded.integer("inner_quality") == 0xFFFFFFFF


def test_r116_spoofinfo_manual_example_and_binary_types() -> None:
    raw = (
        b"#SPOOFINFOA,74,GPS,FINE,2393,217060000,22990,0,18,46;"
        b"NARROW_INT,1,0000000C,00000000,00000521,"
        b"0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
        b"00000006202520E7,000000003000837F,0000000000000000,"
        b"0000000000000000,0.000,0.000,0.000*f9fec019\r\n"
    )
    message = next(
        m for m in StreamDecoder(strict=True).feed(raw) if isinstance(m, AsciiMessage)
    )
    record = Log.SPOOFINFO.decode(message)
    assert record["position_type"] == "NARROW_INT"
    assert record.integer("spoof_indicator") == 1
    assert record.integer("spoof_notice_mask") == 0xC
    assert record.integer("spoof_frequency_mask") == 0x521
    assert record.integer("gps_satellite_notice_mask") == 0x6202520E7
    assert record.integer("bds_satellite_notice_mask") == 0x3000837F
    assert record["field_21"] == record["gps_satellite_notice_mask"]

    binary = cast(BinaryMessage, captured(Log.SPOOFINFO, True))
    payload = bytearray(binary.payload)
    pack_into("<i", payload, 4, -1)
    pack_into("<I", payload, 20, 0xFFFFFFFF)
    pack_into("<Q", payload, 80, 0x8000000000000001)
    decoded = Log.SPOOFINFO.decode(replace(binary, payload=bytes(payload)))
    assert decoded.integer("spoof_indicator") == -1
    assert decoded.integer("field_06") == 0xFFFFFFFF
    assert decoded.integer("gps_satellite_notice_mask") == 0x8000000000000001


@pytest.mark.parametrize("product", ["UM980", "UB9A0", "UM980C", "UM981C"])
def test_r116_single_antenna_group_10(product: str) -> None:
    command = configuration.signal_group(10, product=product)  # type: ignore[arg-type]
    assert command.text == "CONFIG SIGNALGROUP 10"


def test_r116_um982c_signal_groups_and_mask_frequency() -> None:
    for master, slave in ((3, 6), (4, 5), (7, 0)):
        assert configuration.signal_group(master, slave, product="UM982C").text == (
            f"CONFIG SIGNALGROUP {master} {slave}"
        )
    with pytest.raises(ValueError):
        configuration.signal_group(5, 0, product="UM982C")
    assert "L-band" in configuration.SIGNAL_GROUP_BANDS[3]
    for frequency in ("L1CA", "B2I", "BD3B1C", "BD3B2A", "E6C", "Q1CA", "I5"):
        assert masking.frequency(frequency).text == f"MASK {frequency}"
