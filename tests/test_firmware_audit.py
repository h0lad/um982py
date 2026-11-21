from struct import pack

import pytest

from conftest import FIXTURES, ReplayTransport, ascii_message, rtcm
from test_protocol import binary
from um982py import Log, Receiver
from um982py.commands import Port, Trigger
from um982py.errors import ProtocolError
from um982py.experimental import (
    base_mask_report,
    iter_correction_audit,
    observation_mask_report,
)
from um982py.messages import Record, decode_log
from um982py.protocol import StreamDecoder
from um982py.protocol.binary import parse_binary
from um982py.protocol.checksums import nmea_checksum
from um982py.receiver_models import LogList


@pytest.mark.parametrize(
    ("original", "variant"),
    (
        (Log.HWSTATUS, Log.HWSTATUSD),
        (Log.RTCSTATUS, Log.RTCSTATUSD),
        (Log.PVTSLN, Log.PVTSOL),
        (Log.SATECEF, Log.SATXYZ2),
        (Log.SATSINFO, Log.SATINFO),
    ),
)
def test_firmware_variant_preserves_base_layout(original: Log, variant: Log) -> None:
    raw = (FIXTURES / "bodies" / f"{original.wire_name(binary=True)}.bin").read_bytes()
    source = parse_binary(raw)
    payload = source.payload
    message_id = variant.definition.message_id
    assert message_id is not None
    renamed = parse_binary(binary(payload, message_id))
    record = variant.decode(renamed)
    assert record.entries == original.decode(source).entries
    assert variant.read(binary=True).matches(renamed)
    selected = original if variant is Log.SATINFO else variant
    assert decode_log(renamed).name == selected.value


def test_basesats_count_and_native_status() -> None:
    status = 0x01020003
    payload = pack("<IHHfI", 1, 12, 2, 33.5, status)
    (message,) = StreamDecoder(strict=True).feed(binary(payload, 2113))
    record = decode_log(message)
    assert record.name == "BASESATS"
    assert record.integer("count") == 1
    (entry,) = record.records("observations")
    assert entry.entries == (
        ("prn", 12),
        ("field_2", 2),
        ("field_4", 33.5),
        ("status_word", status),
    )
    (text,) = StreamDecoder(strict=True).feed(
        ascii_message("BASESATS", "1,12,2,33.5,01020003")
    )
    assert decode_log(text).entries == record.entries
    assert (
        Log.BASESATS.output(Trigger.ON_CHANGED, binary=True, port=Port.COM2).text
        == "BASESATSB COM2 ONCHANGED"
    )
    with pytest.raises(ProtocolError):
        decode_log(parse_binary(binary(payload[:-1], 2113)))


def test_basesats_subscription_name_round_trip() -> None:
    (message,) = StreamDecoder(strict=True).feed(
        ascii_message("LOGLISTA", "1,BASSATSB COM1 ONCHANGED")
    )
    (entry,) = LogList.from_message(message).entries
    assert entry.name == "BASESATSB"
    assert entry.command().text == "BASESATSB COM1 ONCHANGED"


def test_ssr_tables_preserve_native_entries_and_padding() -> None:
    header = bytes(24) + pack("<I", 1)
    orbit = header + b"ab" + bytes(range(53))
    orbit_record = decode_log(parse_binary(binary(orbit, 11278)))
    assert orbit_record["native_entries"] == (bytes(range(53)),)
    assert orbit_record["native_header"] == header + b"ab"
    assert orbit_record["native_tail"] == b""

    clock = header + bytes(range(25)) + bytes(63 * 25)
    clock_record = decode_log(parse_binary(binary(clock, 11279)))
    assert clock_record["native_entries"] == (bytes(range(25)),)
    assert clock_record["native_tail"] == bytes(63 * 25)
    with pytest.raises(ProtocolError):
        decode_log(parse_binary(binary(orbit[:-1], 11278)))
    with pytest.raises(ProtocolError):
        decode_log(parse_binary(binary(bytes(24) + pack("<I", 65), 11278)))


@pytest.mark.parametrize(
    ("name", "message_id", "header", "body", "row"),
    [
        (
            "SSR1ORBIT",
            11278,
            "G,0,0,0,0,0,0,0,0,1,0,0",
            pack("<Bi6d", 12, 9, 1, -2, 3, 4, 5, 6),
            "12,9,1,-2,3,4,5,6",
        ),
        (
            "SSR1CLOCK",
            11279,
            "G,0,0,0,0,0,0,1",
            pack("<B3d", 12, 1, -2, 3),
            "12,1,-2,3",
        ),
    ],
)
def test_ssr_ascii_and_binary_agree(
    name: str, message_id: int, header: str, body: bytes, row: str
) -> None:
    prefix = bytes(24) + pack("<I", 1)
    if name == "SSR1ORBIT":
        prefix += b"\0\0"
    decoder = StreamDecoder(strict=True)
    binary_message, text = decoder.feed(
        binary(prefix + body, message_id) + ascii_message(name + "A", f"{header},{row}")
    )
    assert decode_log(binary_message).records("satellites") == decode_log(text).records(
        "satellites"
    )


def test_rtcm1032_input_and_receiver_output_in_transcript_order() -> None:
    bits = 0
    for value, width in (
        (1032, 12),
        (1, 12),
        (2, 12),
        (20, 6),
        (-10000, 38),
        (20000, 38),
        (30000, 38),
        (0, 4),
    ):
        bits = (bits << width) | (value & ((1 << width) - 1))
    wire = (
        rtcm(bits.to_bytes(20, "big"))
        + binary(b"", 65000)
        + binary(pack("<4i3d", 0, 1, 2, 20, -1, 2, 3), 2078)
        + ascii_message("RTCM1032A", "0,1,2,20,-1,2,3")
    )
    events = tuple(iter_correction_audit(StreamDecoder(strict=True).feed(wire)))
    assert [event.frame_index for event in events] == [0, 2, 3]
    source, native, text = [event.data for event in events]
    assert isinstance(source, Record)
    assert isinstance(native, Record)
    assert isinstance(text, Record)
    fields = source["fields"]
    assert isinstance(fields, Record)
    assert (fields["DF003"], fields["DF226"], fields["DF021"]) == (1, 2, 20)
    assert fields["DF025"] == native["ecef_x"] == -1.0
    assert native.entries == text.entries
    assert Log.RTCM1032.read(binary=True).text == "RTCM1032B"


@pytest.mark.parametrize(
    ("message_id", "name", "length"),
    [
        (12073, "BBPPSMSG", 108),
        (982, "SBAS2", 116),
        (987, "SBAS3", 116),
        (992, "SBAS4", 116),
        (994, "SBAS5", 116),
        (995, "SBAS6", 228),
        (997, "SBAS9", 104),
        (980, "SBAS17", 108),
        (983, "SBAS24", 132),
        (984, "SBAS25", 132),
        (985, "SBAS26", 144),
        (60032, "SBAS28", 56),
        (1425, "SBASALMANAC", 40),
    ],
)
def test_unmapped_bodies_keep_native_bytes(
    message_id: int, name: str, length: int
) -> None:
    payload = bytes(range(length))
    record = decode_log(parse_binary(binary(payload, message_id)))
    assert record.name == name
    assert record["payload"] == payload
    with pytest.raises(ProtocolError):
        decode_log(parse_binary(binary(payload[:-1], message_id)))


def test_sbas_masks_match_captured_ascii_and_binary() -> None:
    wire = (FIXTURES / "captures-extra" / "SBAS-mask-pairs.bin").read_bytes()
    decoder = StreamDecoder(strict=True)
    prn_ascii, prn_binary, grid_ascii, grid_binary = map(decode_log, decoder.feed(wire))
    decoder.finish()
    assert prn_ascii.entries == prn_binary.entries
    assert prn_binary["source_prn"] == 136
    assert prn_binary["prn_mask"] == bytes.fromhex(
        "ffffffff0000000000000000000000800100000000000000000000"
    )
    assert grid_ascii.entries == grid_binary.entries
    assert grid_binary["source_prn"] == 136
    assert grid_binary["grid_mask"] == bytes.fromhex(
        "0000001fffffc000000007ffc000007ffc000007ffe000fc0000"
    )


def _config(body: bytes) -> bytes:
    line = b"$CONFIG," + body
    return line + f"*{nmea_checksum(line):02X}\r\n".encode()


def test_collect_mask_reports() -> None:
    base = base_mask_report()
    obs = observation_mask_report()
    transport = ReplayTransport(
        {
            base.encode(): _config(b"MASKBASE,GPSMaskPrn:1,8,")
            + _config(b"MASKBASE,GALMaskPrn:2,"),
            obs.encode(): _config(b"MASKOBS,MASKOBS 10.0 GPS")
            + _config(b"MASKOBS,MASKOBS L2"),
        }
    )
    with Receiver(transport) as receiver:
        gps, gal = receiver.collect(base, quiet=0.01)
        threshold, signal = receiver.collect(obs, quiet=0.01)
    assert gps["system"] == "GPS" and gps["prns"] == (1, 8)
    assert gal["system"] == "GAL" and gal["prns"] == (2,)
    assert threshold["native_threshold"] == 10.0
    assert threshold["native_label"] == "GPS"
    assert signal["native_label"] == "L2"
