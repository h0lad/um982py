"""Documented receiver status logs and message inventory."""

import json
from dataclasses import replace
from struct import pack_into
from typing import cast

import pytest

from conftest import FIXTURES
from test_extended_logs import captured
from um982py import decode_message
from um982py.commands import Log, configuration, masking
from um982py.commands.catalog import LOGS, RTCM_LOGS
from um982py.messages import (
    AsciiMessage,
    BinaryMessage,
    PpsStatus,
    Record,
    SpoofInfo,
    SpoofNotice,
    SpoofSignal,
    SpoofTimeNotice,
)
from um982py.protocol import StreamDecoder

MANUAL_EXAMPLES = json.loads((FIXTURES / "manual-examples.json").read_text())


@pytest.mark.parametrize("wire", MANUAL_EXAMPLES.values(), ids=MANUAL_EXAMPLES.keys())
def test_checksum_valid_manual_example(wire: str) -> None:
    assert decode_message((wire + "\r\n").encode()).message is not None


def test_inventory_sections() -> None:
    reference = json.loads((FIXTURES / "receiver-reference.json").read_text())
    entries = reference["logs"]
    names = {entry["name"] for entry in entries}
    assert len(names) == len(entries)
    assert names == LOGS.keys() - RTCM_LOGS.keys()
    sections = {
        item["section"] for item in entries if item["section"].startswith("7.5.")
    }
    assert sections == {f"7.5.{n}" for n in range(2, 104) if n not in (10, 85)}
    for item in entries:
        definition = Log[item["name"]].definition
        assert definition.section == item["section"]
        assert definition.message_id == item["message_id"]


def test_ppsstatus_manual_example() -> None:
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
    assert "field_02" not in record
    status = PpsStatus.from_record(record)
    assert status.config.interval == 1000
    assert status.config.mode == 0
    assert status.config.falling_edge is False
    assert status.config.gnss_reference == 1
    assert status.control_register == 5
    assert status.pulse_control_register == 1
    assert status.current_pps_delay == 0xD2BC
    assert status.time_reference == 1
    assert status.config_flag == 1
    assert (status.quality.position, status.quality.gps, status.quality.bds) == (
        9,
        6,
        6,
    )
    assert (status.quality.galileo, status.quality.glonass, status.quality.irnss) == (
        6,
        6,
        4,
    )
    binary = cast(BinaryMessage, captured(Log.PPSSTATUS, True))
    payload = bytearray(binary.payload)
    pack_into("<i", payload, 12, -123)
    pack_into("<I", payload, 32, 0xFFFFFFFF)
    decoded = Log.PPSSTATUS.decode(replace(binary, payload=bytes(payload)))
    assert decoded.integer("pulse_error_ns") == -123
    assert decoded.integer("inner_quality") == 0xFFFFFFFF


def test_spoofinfo_manual_example_and_binary_types() -> None:
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
    assert "field_21" not in record
    info = SpoofInfo.from_record(record)
    assert info.notices == SpoofNotice.TRACKED_SATELLITES | SpoofNotice.SIGNAL_SOURCE
    assert info.time_notices == SpoofTimeNotice(0)
    assert info.signals == (
        SpoofSignal.BDS_B1I
        | SpoofSignal.BDS_B3I
        | SpoofSignal.GPS_L1CA
        | SpoofSignal.GPS_L2C
    )
    assert info.bds_satellites == (1, 2, 3, 4, 5, 6, 7, 9, 10, 16, 29, 30)

    binary = cast(BinaryMessage, captured(Log.SPOOFINFO, True))
    payload = bytearray(binary.payload)
    pack_into("<i", payload, 4, -1)
    pack_into("<I", payload, 20, 0xFFFFFFFF)
    pack_into("<Q", payload, 80, 0x8000000000000001)
    decoded = Log.SPOOFINFO.decode(replace(binary, payload=bytes(payload)))
    assert decoded.integer("spoof_indicator") == -1
    assert decoded.integer("reserved_1") == 0xFFFFFFFF
    assert decoded.integer("gps_satellite_notice_mask") == 0x8000000000000001
    assert SpoofInfo.from_record(decoded).gps_satellites == (1, 64)


def test_status_flags_preserve_reserved_bits_and_validate_masks() -> None:
    message = cast(BinaryMessage, captured(Log.SPOOFINFO, True))
    payload = bytearray(message.payload)
    pack_into("<III", payload, 8, 0x80000001, 0x80000004, 0x80008001)
    record = Log.SPOOFINFO.decode(replace(message, payload=bytes(payload)))
    info = SpoofInfo.from_record(record)
    assert int(info.notices) == 0x80000001
    assert info.time_notices & SpoofTimeNotice.GALILEO
    assert info.signals & SpoofSignal.GLONASS_G1
    assert int(info.signals) == 0x80008001
    with pytest.raises(ValueError, match="SPOOFINFO"):
        SpoofInfo.from_record(Record("PPSSTATUS", ()))
    with pytest.raises(ValueError, match="PPSSTATUS"):
        PpsStatus.from_record(Record("SPOOFINFO", ()))


def test_pps_status_packed_words() -> None:
    binary = cast(BinaryMessage, captured(Log.PPSSTATUS, True))
    payload = bytearray(binary.payload)
    pack_into("<I", payload, 24, 0xED)
    pack_into("<III", payload, 36, 0x56341200, 0xABDCBA98, 0x44332211)
    status = PpsStatus.from_record(
        Log.PPSSTATUS.decode(replace(binary, payload=bytes(payload)))
    )
    assert (status.control_register, status.pulse_control_register) == (13, 14)
    assert (status.inner_system, status.inner_control_flag, status.inner_state) == (
        0x12,
        0x34,
        0x56,
    )
    assert (status.current_pps_delay, status.time_reference, status.config_flag) == (
        0xCBA98,
        0xD,
        0xAB,
    )
    assert (
        status.stable_count,
        status.switch_count,
        status.keep_count,
        status.hold_count,
    ) == (
        0x11,
        0x22,
        0x33,
        0x44,
    )


@pytest.mark.parametrize("product", ["UM980", "UB9A0", "UM980C", "UM981C"])
def test_single_antenna_group_10(product: str) -> None:
    command = configuration.signal_group(10, product=product)  # type: ignore[arg-type]
    assert command.text == "CONFIG SIGNALGROUP 10"


def test_um982c_signal_groups_and_mask_frequency() -> None:
    for master, slave in ((3, 6), (4, 5), (7, 0)):
        assert configuration.signal_group(master, slave, product="UM982C").text == (
            f"CONFIG SIGNALGROUP {master} {slave}"
        )
    with pytest.raises(ValueError):
        configuration.signal_group(5, 0, product="UM982C")
    assert "L-band" in configuration.SIGNAL_GROUP_BANDS[3]
    for frequency in ("L1CA", "B2I", "BD3B1C", "BD3B2A", "E6C", "Q1CA", "I5"):
        assert masking.frequency(frequency).text == f"MASK {frequency}"
